/**
 * Google Apps Script Webhook handler
 * Automatically appends incoming activities from PyLab into the spreadsheet
 *
 * To Setup:
 * 1. Open a Google Sheet.
 * 2. Go to Extensions -> Apps Script.
 * 3. Delete any code in Code.gs and paste this script.
 * 4. Save the project (e.g. name it "PyLab Log Webhook").
 * 5. Click Deploy -> New deployment.
 * 6. Under select type, select "Web app".
 * 7. Set Description to "PyLab Activity Logger".
 * 8. Set Execute as: "Me" (your email).
 * 9. Set Who has access: "Anyone".
 * 10. Click Deploy and copy the Web App URL.
 * 11. Put that URL into the GOOGLE_SCRIPT_URL field in your PyLab .env file.
 */

function doPost(e) {
  try {
    // Parse the payload sent from the Flask backend
    var jsonString = e.postData.contents;
    var data = JSON.parse(jsonString);
    
    // Get the active spreadsheet sheet named "Sheet1" (or the first active sheet)
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
    
    // If the sheet is completely empty, append header columns first
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(["User", "Email", "Action", "Timestamp"]);
      
      // Style headers: bold and background color
      var headerRange = sheet.getRange(1, 1, 1, 4);
      headerRange.setFontWeight("bold");
      headerRange.setBackground("#0f172a");
      headerRange.setFontColor("#00d4ff");
    }
    
    // Extract variables with support for various key case stylings
    var user = data.username || data.User || "anonymous";
    var email = data.email || data.Email || "N/A";
    var action = data.action || data.Action || "unknown";
    var timestamp = data.timestamp || data.Timestamp || new Date().toISOString();
    
    // Format timestamp representation slightly for readability in the sheet
    if (timestamp.includes("T")) {
      // Reformat standard ISO dates for Sheet cell ease
      timestamp = timestamp.replace("T", " ").split(".")[0];
    }
    
    // Append the row values
    sheet.appendRow([user, email, action, timestamp]);
    
    // Auto-fit column widths
    for (var col = 1; col <= 4; col++) {
      sheet.autoResizeColumn(col);
    }
    
    // Return a successful JSON response
    return ContentService.createTextOutput(JSON.stringify({
      "status": "success",
      "message": "Activity log appended to Google Sheet successfully!"
    })).setMimeType(ContentService.MimeType.JSON);
    
  } catch(error) {
    // Return error information in JSON
    return ContentService.createTextOutput(JSON.stringify({
      "status": "error",
      "message": error.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

// Simple test function to run and authorize sheet permissions in standard execution
function testSetup() {
  Logger.log("Apps Script spreadsheet permissions verified!");
}
