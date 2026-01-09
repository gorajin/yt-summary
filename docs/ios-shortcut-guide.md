# iOS Shortcut Setup Guide

Create an iOS shortcut that lets you share YouTube videos directly to Notion.

## Step-by-Step Setup

### 1. Open Shortcuts App

Open the **Shortcuts** app on your iPhone (comes pre-installed).

### 2. Create New Shortcut

1. Tap **+** in the top right
2. Tap **Add Action**

### 3. Add Actions

Add these actions in order:

---

#### Action 1: Receive Input

1. Search for **"Receive"**
2. Select **"Receive input from Share Sheet"** (might be auto-added)
3. Tap **"Any"** and select only **"URLs"**

---

#### Action 2: Get URLs from Input

1. Search for **"URL"**
2. Select **"Get URLs from Input"**

---

#### Action 3: Get Contents of URL (HTTP Request)

1. Search for **"Get Contents"**
2. Select **"Get Contents of URL"**
3. Configure:
   - **URL**: `https://YOUR-RAILWAY-APP.up.railway.app/summarize`
   - **Method**: `POST`
   - **Headers**: Add header
     - Key: `Content-Type`
     - Value: `application/json`
   - **Request Body**: `JSON`
     - Add new field:
       - Key: `url`
       - Type: Text
       - Value: Select **"URLs"** from the magic variable (from step 2)

---

#### Action 4: Show Notification

1. Search for **"Notification"**
2. Select **"Show Notification"**
3. Set message to: `✅ Saved to Notion!`

---

### 4. Name Your Shortcut

1. Tap the dropdown at the top
2. Name it **"Save to Notion"** (or whatever you prefer)
3. Tap **"Done"**

---

## How to Use

1. **Watch any YouTube video** on your iPhone
2. Tap **Share** button
3. Scroll down and tap **"Save to Notion"**
4. Wait for confirmation notification
5. Open Notion to see your organized notes!

---

## Troubleshooting

### "Could not connect to server"
- Make sure your Railway app is deployed and running
- Check the URL in the shortcut matches your Railway app URL

### "No transcript available"
- Some videos don't have captions/transcripts
- Live streams and very new videos may not have transcripts yet

### Notion page not appearing
- Verify your Notion Integration is connected to the database
- Check that the database has the correct property names: `title`, `URL`, `Added`

---

## Visual Reference

The shortcut should look like this when complete:

```
┌─────────────────────────────────────┐
│ Receive input from Share Sheet     │
│ └─ URLs                             │
├─────────────────────────────────────┤
│ Get URLs from                       │
│ └─ Shortcut Input                   │
├─────────────────────────────────────┤
│ Get Contents of URL                 │
│ └─ POST https://your-app.../summarize│
│ └─ Body: {"url": URLs}              │
├─────────────────────────────────────┤
│ Show Notification                   │
│ └─ ✅ Saved to Notion!              │
└─────────────────────────────────────┘
```
