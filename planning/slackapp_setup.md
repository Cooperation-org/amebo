Slack App Setup Checklist
1. Create App
Go to https://api.slack.com/apps
Click "Create New App" → "From scratch"
Name: Slack Helper Bot
Choose your workspace

2. OAuth & Permissions (Required Scopes)
Add these Bot Token Scopes: Messages & Channels:
channels:history - Read public channel messages
channels:read - View basic channel info
groups:history - Read private channel messages
groups:read - View private channels
im:history - Read DMs (optional)
mpim:history - Read group DMs (optional)
Users:
users:read - View user info
users:read.email - View email addresses
Files:
files:read - Access file info
Reactions:
reactions:read - View reactions
Other:
bookmarks:read - Read channel bookmarks
team:read - View workspace info

3. Event Subscriptions (for real-time collection)
Enable Events and subscribe to:
message.channels - Messages in public channels
message.groups - Messages in private channels
reaction_added - New reactions
reaction_removed - Removed reactions
message_changed - Edited messages
message_deleted - Deleted messages
channel_created - New channels
user_change - User profile updates

4. Socket Mode (easier for development)
Enable Socket Mode
Generate an App-Level Token (starts with xapp-)

5. Install App
Install to your workspace
Copy the Bot User OAuth Token (starts with xoxb-)

6. Add Bot to Channels
The bot only sees channels it's added to!
Once you have the tokens, paste them in your .env file:
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...