/**
 * Google Apps Script Webhook handler (Multi-Table Version)
 * Automatically creates tabs and logs incoming behavior analytics from PyLab.
 *
 * To Setup/Update:
 * 1. Open your Google Sheet.
 * 2. Go to Extensions -> Apps Script.
 * 3. Delete any code in Code.gs and paste this script.
 * 4. Save the project.
 * 5. Click Deploy -> Manage deployments.
 * 6. Click the pencil icon next to your active deployment and choose Version: "New version".
 * 7. Click Deploy and copy the Web App URL (if it changes).
 * 8. Verify the URL is in your PyLab .env file as GOOGLE_SCRIPT_URL.
 */

function doPost(e) {
  try {
    // Parse the payload sent from the Flask backend
    var jsonString = e.postData.contents;
    var payload = JSON.parse(jsonString);
    
    // Support either structured table format or direct backward-compatible format
    var table = payload.table || "activity_logs";
    var data = payload.data || payload;
    
    // Get targeted tab/sheet name
    var sheetName = getSheetNameForTable(table);
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = ss.getSheetByName(sheetName);
    
    // If the tab doesn't exist, create it dynamically
    if (!sheet) {
      sheet = ss.insertSheet(sheetName);
    }
    
    // If the tab has no rows, add standard formatted headers
    if (sheet.getLastRow() === 0) {
      var headers = getHeadersForTable(table);
      sheet.appendRow(headers);
      
      // Style headers: bold and slate background with cyan text
      var headerRange = sheet.getRange(1, 1, 1, headers.length);
      headerRange.setFontWeight("bold");
      headerRange.setBackground("#0f172a");
      headerRange.setFontColor("#00d4ff");
    }
    
    // Map data values and append the log entry row
    var rowValues = getRowValues(table, data);
    sheet.appendRow(rowValues);
    
    // Auto-fit column widths
    for (var col = 1; col <= rowValues.length; col++) {
      sheet.autoResizeColumn(col);
    }
    
    // Return a successful JSON response
    return ContentService.createTextOutput(JSON.stringify({
      "status": "success",
      "message": "Appended record to " + sheetName + " tab successfully!"
    })).setMimeType(ContentService.MimeType.JSON);
    
  } catch(error) {
    // Return error information in JSON
    return ContentService.createTextOutput(JSON.stringify({
      "status": "error",
      "message": error.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

// ── Helper Mapping Functions ──

function getSheetNameForTable(table) {
  switch (table) {
    case "activity_logs": return "Activity Logs";
    case "code_runs": return "Code Runs";
    case "user_sessions": return "User Sessions";
    case "ai_hint_usage": return "AI Hint Usage";
    case "project_progress": return "Project Progress";
    default: return "Activity Logs";
  }
}

function getHeadersForTable(table) {
  switch (table) {
    case "activity_logs": return ["User", "Email", "Action", "Timestamp"];
    case "code_runs": return ["User", "Project Name", "Success", "Ran At"];
    case "user_sessions": return ["User", "Started At"];
    case "ai_hint_usage": return ["User", "Project Name", "Hint Used At"];
    case "project_progress": return ["User", "Project Name", "Completed", "Time Spent (Mins)"];
    default: return ["User", "Email", "Action", "Timestamp"];
  }
}

function getRowValues(table, data) {
  var user = data.username || data.User || "anonymous";
  
  function formatDate(dStr) {
    if (!dStr) return new Date().toISOString().replace("T", " ").split(".")[0];
    return dStr.replace("T", " ").split(".")[0];
  }
  
  switch (table) {
    case "activity_logs":
      return [
        user,
        data.email || "N/A",
        data.action || "unknown",
        formatDate(data.timestamp)
      ];
    case "code_runs":
      return [
        user,
        data.project_name || "unknown",
        data.success !== undefined ? String(data.success) : "N/A",
        formatDate(data.ran_at)
      ];
    case "user_sessions":
      return [
        user,
        formatDate(data.started_at)
      ];
    case "ai_hint_usage":
      return [
        user,
        data.project_name || "unknown",
        formatDate(data.hint_used_at)
      ];
    case "project_progress":
      return [
        user,
        data.project_name || "unknown",
        data.completed !== undefined ? String(data.completed) : "N/A",
        data.time_spent_mins !== undefined ? String(data.time_spent_mins) : "0"
      ];
    default:
      return [
        user,
        data.email || "N/A",
        data.action || "unknown",
        formatDate(data.timestamp)
      ];
  }
}

// Simple test function to run and authorize spreadsheet permissions
function testSetup() {
  Logger.log("Apps Script spreadsheet permissions verified!");
}
