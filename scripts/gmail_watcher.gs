/**
 * gmail_watcher.gs — NovoDia interview evaluation pipeline
 *
 * Runs on a 5-minute time trigger in Google Workspace. It watches the HR inbox
 * for candidate replies to the "short video submission" request email, finds the
 * matching Airtable Submission record, and kicks off automatic evaluation:
 *
 *   - If the candidate attached an MP4 -> upload it to Google Drive and tell the
 *     Railway /ingest endpoint to score it.
 *   - If the candidate pasted a YouTube link -> send that link to /ingest.
 *   - If the candidate replied with no video at all -> flag the record for human
 *     review in Airtable and email HR.
 *
 * Secrets live in Script Properties (File > Project Settings > Script Properties),
 * never in this file. Required properties:
 *   AIRTABLE_TOKEN  — Airtable Personal Access Token
 *   WEBHOOK_SECRET  — shared secret for the Railway /ingest X-Webhook-Secret header
 */

// ---------------------------------------------------------------------------
// CONFIGURATION — safe, non-secret identifiers
// ---------------------------------------------------------------------------

var AIRTABLE_BASE_ID = "app2HZvbePXlH9xLX";
var APPLICATIONS_TABLE_ID = "tblEsA1ZVdJdRLbs1";
var SUBMISSIONS_TABLE_ID = "tblAjBCyfful0jay0";

// Field identifiers on the Submissions table.
var SUBMISSION_APPLICATION_FIELD_ID = "fldYAiyp0ILBXGuiQ"; // "Application" link field
var SUBMISSION_SCORE1_FIELD_ID = "fldPHxOA56TRIsEXq";      // "Score 1" field
var SUBMISSION_REVIEW_NEEDED_FIELD = "Review Needed";       // display name

// Airtable REST base URL.
var AIRTABLE_API_BASE = "https://api.airtable.com/v0";

// Railway ingest endpoint that starts the scoring pipeline.
var RAILWAY_INGEST_URL = "https://airtableintegration-production.up.railway.app/ingest";

// Gmail subject of the reply we are looking for.
var REPLY_SUBJECT = "Re: Next step in your NovoDia application: short video submission";

// Google Drive folder where MP4 attachments are uploaded.
var DRIVE_FOLDER_ID = "1GzhsnpTYcGZsiKoDx9ID0UwOkF4ZSrES";

// Where to send "candidate replied without a video" notifications.
var HR_NOTIFICATION_EMAIL = "lily.nir@novodia.co";

// Email domain used by NovoDia team members. Emails from this domain are
// treated as potential forwards, not direct candidate replies.
var TEAM_DOMAIN = "@novodia.co";


// ---------------------------------------------------------------------------
// MAIN — runs every 5 minutes
// ---------------------------------------------------------------------------

/**
 * Entry point. Scans recent unread reply emails and processes each one.
 */
function checkVideoReplies() {
  // Load secrets once per run.
  var props = PropertiesService.getScriptProperties();
  var airtableToken = props.getProperty("AIRTABLE_TOKEN");
  var webhookSecret = props.getProperty("WEBHOOK_SECRET");

  if (!airtableToken || !webhookSecret) {
    console.log("ERROR: Missing AIRTABLE_TOKEN or WEBHOOK_SECRET in Script Properties. Aborting.");
    return;
  }

  // Find candidate reply threads from the last 7 days that we have not read yet.
  var query = 'subject:"' + REPLY_SUBJECT + '" is:unread newer_than:7d';
  var threads = GmailApp.search(query);
  console.log("Found " + threads.length + " matching thread(s).");

  // Process each thread independently so one failure cannot stop the batch.
  for (var t = 0; t < threads.length; t++) {
    try {
      // Only the latest message in the thread is the candidate's newest reply.
      var messages = threads[t].getMessages();
      var msg = messages[messages.length - 1];

      // Skip messages we have already handled.
      if (!msg.isUnread()) {
        continue;
      }

      processMessage(msg, airtableToken, webhookSecret);
    } catch (err) {
      console.log("ERROR processing thread " + t + ": " + err);
    }
  }
}


/**
 * Handle a single candidate reply message end-to-end.
 * Handles two sender types:
 *   - Direct candidate replies (sender is not @novodia.co)
 *   - Forwarded candidate replies (sender is @novodia.co; original sender extracted from body)
 * Internal team chatter (no valid candidate payload) is silently skipped.
 */
function processMessage(msg, airtableToken, webhookSecret) {
  // --- Classify sender: direct reply vs. forward vs. internal chatter --------
  var senderEmail = parseEmail(msg.getFrom());
  var plainBody = msg.getPlainBody() || "";

  var senderInfo = classifySender(senderEmail, plainBody);
  if (!senderInfo) {
    // Internal team chatter — no candidate payload found; skip quietly.
    console.log("Skipping internal chatter / unrecognised forward from: " + senderEmail);
    msg.markRead();
    return;
  }

  var candidateEmail = senderInfo.candidateEmail;
  var isForward = senderInfo.isForward;
  console.log("Processing " + (isForward ? "forwarded" : "direct") + " reply. Candidate: " + candidateEmail);

  // --- Find the Airtable Submission record to attach this video to ------------
  var recordId = findSubmissionRecord(candidateEmail, airtableToken);
  if (!recordId) {
    console.log("No matching unscored Submission found for " + candidateEmail + ". Marking read and skipping.");
    msg.markRead();
    return;
  }
  console.log("Matched Submission record: " + recordId);

  // --- Detect the video source ------------------------------------------------
  // GmailApp.getAttachments() returns forwarded attachments at the message level,
  // so findVideoAttachment() works identically for direct replies and forwards.
  var attachments = msg.getAttachments();
  var videoAttachment = findVideoAttachment(attachments);
  var youtubeUrl = findYouTubeUrl(plainBody);

  if (videoAttachment) {
    // Path A: MP4 attachment → upload to Drive, then trigger ingest.
    console.log("Found video attachment: " + videoAttachment.getName());
    var downloadUrl = uploadToDrive(videoAttachment, candidateEmail);
    triggerIngest(recordId, "gdrive", downloadUrl, videoAttachment.getName(), webhookSecret);

  } else if (youtubeUrl) {
    // Path A: YouTube link → trigger ingest directly with the URL.
    console.log("Found YouTube URL: " + youtubeUrl);
    triggerIngest(recordId, "youtube", youtubeUrl, null, webhookSecret);

  } else {
    // Path B: no video → flag for human review and notify HR.
    console.log("No video found in reply. Flagging for review.");
    flagForReview(recordId, plainBody, candidateEmail, airtableToken);
  }

  // --- Done: mark handled so we do not reprocess it next run ------------------
  msg.markRead();
}


// ---------------------------------------------------------------------------
// SENDER CLASSIFICATION — direct reply vs. forwarded vs. internal chatter
// ---------------------------------------------------------------------------

/**
 * Determine whether the email is a direct candidate reply, a valid forwarded
 * candidate reply, or internal team chatter.
 *
 * Returns {candidateEmail, isForward} for processable emails,
 * or null for internal chatter that should be skipped.
 */
function classifySender(senderEmail, plainBody) {
  if (!senderEmail.endsWith(TEAM_DOMAIN)) {
    // Direct reply from a candidate (sender is not @novodia.co).
    return { candidateEmail: senderEmail, isForward: false };
  }

  // Sender is a team member — look for a forwarded candidate payload.
  var forwardedEmail = extractCandidateEmailFromForward(plainBody);
  if (forwardedEmail) {
    return { candidateEmail: forwardedEmail, isForward: true };
  }

  // No valid candidate payload found — this is internal chatter.
  return null;
}

/**
 * Extract the original candidate's email address from a forwarded message body.
 *
 * Handles three common forward formats:
 *   1. Gmail:      "---------- Forwarded message ---------\nFrom: ..."
 *   2. Apple Mail: "Begin forwarded message:\nFrom: ..."
 *   3. Bare quote: "On [date], Name <email> wrote:"
 *
 * Returns the candidate email string (lowercased), or null if:
 *   - No recognisable forwarded block is found, OR
 *   - The extracted email ends in @novodia.co (internal chain, not a candidate).
 */
function extractCandidateEmailFromForward(plainBody) {
  if (!plainBody) return null;

  var fromLine = null;

  // Pattern 1: Gmail-style forward header
  var gmailMatch = plainBody.match(/------+\s*Forwarded message\s*------+[\s\S]*?From:\s*([^\n]+)/i);
  if (gmailMatch) {
    fromLine = gmailMatch[1];
  }

  // Pattern 2: Apple Mail / Outlook-style forward
  if (!fromLine) {
    var appleMatch = plainBody.match(/Begin forwarded message:[\s\S]*?From:\s*([^\n]+)/i);
    if (appleMatch) {
      fromLine = appleMatch[1];
    }
  }

  // Pattern 3: Bare inline quote — "On [date], Name <email> wrote:"
  // Captures everything between the last date comma and "wrote:".
  if (!fromLine) {
    var bareMatch = plainBody.match(/On\s+[^\n]+?,\s+([^\n]+?)\s+wrote:/i);
    if (bareMatch) {
      fromLine = bareMatch[1];
    }
  }

  if (!fromLine) return null;

  // Extract the email address from the From line.
  var candidateEmail = null;
  var angleMatch = fromLine.match(/<([^>]+)>/);
  if (angleMatch) {
    candidateEmail = angleMatch[1].trim().toLowerCase();
  } else {
    var bareEmailMatch = fromLine.match(/([a-zA-Z0-9._%-]+@[a-zA-Z0-9.-]+)/);
    if (bareEmailMatch) {
      candidateEmail = bareEmailMatch[1].trim().toLowerCase();
    }
  }

  if (!candidateEmail) return null;

  // Reject @novodia.co addresses — forwarded internal chain, not a candidate.
  if (candidateEmail.endsWith(TEAM_DOMAIN)) return null;

  return candidateEmail;
}


// ---------------------------------------------------------------------------
// SENDER PARSING
// ---------------------------------------------------------------------------

/**
 * Extract a bare email address from a Gmail "From" header.
 * Accepts both "Display Name <email@x.com>" and "email@x.com".
 */
function parseEmail(fromHeader) {
  if (!fromHeader) {
    return "";
  }
  var match = fromHeader.match(/<([^>]+)>/);
  if (match) {
    return match[1].trim().toLowerCase();
  }
  return fromHeader.trim().toLowerCase();
}


// ---------------------------------------------------------------------------
// VIDEO DETECTION
// ---------------------------------------------------------------------------

/**
 * Return the first attachment that looks like a video, or null if none.
 * Matches on MIME type "video/*" or a ".mp4" filename.
 */
function findVideoAttachment(attachments) {
  for (var i = 0; i < attachments.length; i++) {
    var att = attachments[i];
    var contentType = (att.getContentType() || "").toLowerCase();
    var name = (att.getName() || "").toLowerCase();
    if (contentType.indexOf("video/") === 0 || name.slice(-4) === ".mp4") {
      return att;
    }
  }
  return null;
}

/**
 * Find the first YouTube URL in the email body, or null if none.
 * Matches both youtube.com/watch?v=... and youtu.be/... forms.
 */
function findYouTubeUrl(body) {
  var pattern = /(https?:\/\/)?(www\.)?(youtube\.com\/watch\?v=[\w-]+|youtu\.be\/[\w-]+)/i;
  var match = body.match(pattern);
  if (!match) {
    return null;
  }
  var url = match[0];
  // Normalize to an absolute URL so the downstream service can fetch it.
  if (url.indexOf("http") !== 0) {
    url = "https://" + url;
  }
  return url;
}


// ---------------------------------------------------------------------------
// AIRTABLE LOOKUP — two steps: Application by email, then unscored Submission
// ---------------------------------------------------------------------------

/**
 * Find the Submission record ID for this candidate's pending video.
 * Returns the record ID string, or null if no match.
 */
function findSubmissionRecord(senderEmail, token) {
  // Step 1: find the Application whose Email matches the sender.
  var applicationId = findApplicationByEmail(senderEmail, token);
  if (!applicationId) {
    console.log("No Application found for email: " + senderEmail);
    return null;
  }

  // Step 2: find the first unscored Submission linked to that Application.
  return findUnscoredSubmission(applicationId, token);
}

/**
 * Step 1 — look up an Application record by its Email field.
 */
function findApplicationByEmail(senderEmail, token) {
  var formula = '{Email}="' + senderEmail + '"';
  var url = AIRTABLE_API_BASE + "/" + AIRTABLE_BASE_ID + "/" + APPLICATIONS_TABLE_ID +
    "?filterByFormula=" + encodeURIComponent(formula) +
    "&fields[]=Email" +
    "&pageSize=1";

  var json = airtableGet(url, token);
  if (json && json.records && json.records.length > 0) {
    return json.records[0].id;
  }
  return null;
}

/**
 * Step 2 — look up the first unscored Submission linked to an Application.
 * "Unscored" means the Score 1 field is empty.
 *
 * Note: Airtable's filterByFormula engine evaluates {Application} as the
 * primary-field display text of linked records, NOT as record IDs. We cannot
 * filter by record ID in the formula. Instead, fetch all unscored Submissions
 * and compare the Application field values (which ARE record IDs in the API
 * response) in JavaScript.
 */
function findUnscoredSubmission(applicationId, token) {
  var formula = '{Score 1}=""';
  var url = AIRTABLE_API_BASE + "/" + AIRTABLE_BASE_ID + "/" + SUBMISSIONS_TABLE_ID +
    "?filterByFormula=" + encodeURIComponent(formula) +
    "&returnFieldsByFieldId=true" +
    "&fields[]=" + SUBMISSION_APPLICATION_FIELD_ID +
    "&fields[]=" + SUBMISSION_SCORE1_FIELD_ID +
    "&pageSize=100";

  var json = airtableGet(url, token);
  if (!json || !json.records) {
    return null;
  }

  // The Application field value in the API response is always an array of
  // Airtable record IDs, regardless of returnFieldsByFieldId.
  for (var i = 0; i < json.records.length; i++) {
    var rec = json.records[i];
    var appLinks = rec.fields[SUBMISSION_APPLICATION_FIELD_ID];
    if (Array.isArray(appLinks) && appLinks.indexOf(applicationId) !== -1) {
      return rec.id;
    }
  }

  console.log("No unscored Submission linked to Application " + applicationId);
  return null;
}

/**
 * Perform an authenticated Airtable GET and return the parsed JSON, or null.
 */
function airtableGet(url, token) {
  var response = UrlFetchApp.fetch(url, {
    method: "get",
    headers: { "Authorization": "Bearer " + token },
    muteHttpExceptions: true,
  });
  var code = response.getResponseCode();
  if (code !== 200) {
    console.log("WARNING: Airtable GET returned " + code + ": " + response.getContentText());
    return null;
  }
  return JSON.parse(response.getContentText());
}


// ---------------------------------------------------------------------------
// DRIVE UPLOAD
// ---------------------------------------------------------------------------

/**
 * Upload a video attachment to the configured Drive folder and return a public
 * direct-download URL the ingest service can fetch.
 */
function uploadToDrive(attachment, senderEmail) {
  var folder = DriveApp.getFolderById(DRIVE_FOLDER_ID);

  // Copy the attachment bytes into a new Drive file.
  var file = folder.createFile(attachment.copyBlob());

  // Give the file an identifiable name (candidate + original filename).
  file.setName(senderEmail + "_" + attachment.getName());

  // Make it accessible to anyone with the link so the pipeline can download it.
  file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);

  var fileId = file.getId();
  console.log("Uploaded to Drive, file ID: " + fileId);
  return "https://drive.google.com/uc?export=download&id=" + fileId;
}


// ---------------------------------------------------------------------------
// RAILWAY INGEST
// ---------------------------------------------------------------------------

/**
 * Tell the Railway pipeline to ingest and score a video.
 */
function triggerIngest(recordId, sourceType, sourceUrl, filename, webhookSecret) {
  var response = UrlFetchApp.fetch(RAILWAY_INGEST_URL, {
    method: "post",
    contentType: "application/json",
    headers: { "X-Webhook-Secret": webhookSecret },
    payload: JSON.stringify({
      record_id: recordId,
      source_type: sourceType, // "gdrive" or "youtube"
      source_url: sourceUrl,
      filename: filename || null,
    }),
    muteHttpExceptions: true,
  });

  var code = response.getResponseCode();
  console.log("Ingest POST for " + recordId + " returned " + code);
  if (code !== 202) {
    console.log("WARNING: unexpected ingest response: " + response.getContentText());
  }
}


// ---------------------------------------------------------------------------
// REVIEW FLAGGING (no video in reply)
// ---------------------------------------------------------------------------

/**
 * Mark a Submission as needing human review and email HR with the reply text.
 */
function flagForReview(recordId, replyText, senderEmail, token) {
  // PATCH the Submission record to set Review Needed = true.
  var url = AIRTABLE_API_BASE + "/" + AIRTABLE_BASE_ID + "/" + SUBMISSIONS_TABLE_ID + "/" + recordId;
  var fields = {};
  fields[SUBMISSION_REVIEW_NEEDED_FIELD] = true;

  var response = UrlFetchApp.fetch(url, {
    method: "patch",
    contentType: "application/json",
    headers: { "Authorization": "Bearer " + token },
    payload: JSON.stringify({ fields: fields }),
    muteHttpExceptions: true,
  });

  var code = response.getResponseCode();
  if (code !== 200) {
    console.log("WARNING: failed to flag record " + recordId + " (" + code + "): " + response.getContentText());
  } else {
    console.log("Flagged record " + recordId + " for review.");
  }

  // Notify HR so a human can follow up with the candidate.
  GmailApp.sendEmail(
    HR_NOTIFICATION_EMAIL,
    "Video Submission: Candidate replied without a video",
    "Sender: " + senderEmail + "\n\nReply text:\n" + (replyText || "").substring(0, 1000)
  );
}


// ---------------------------------------------------------------------------
// SETUP — run once manually to register the trigger
// ---------------------------------------------------------------------------

/**
 * One-time setup: register the 5-minute time-based trigger for checkVideoReplies.
 * Run this manually from the Apps Script editor a single time.
 */
function createTimeTrigger() {
  ScriptApp.newTrigger("checkVideoReplies")
    .timeBased()
    .everyMinutes(5)
    .create();
  console.log("Time trigger created: checkVideoReplies every 5 minutes.");
}
