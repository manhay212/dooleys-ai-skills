---
name: dooleys-twitter-x-reader
description: Fetch tweets from Twitter/X API v2. Use this skill when you need to retrieve user tweets or home timeline from Twitter. Supports fetching tweets from specific users listed in handles.json or getting the authenticated user's home timeline feed.
version: 1.0.0
---

# Twitter/X Reader Skill

This skill provides functionality to fetch tweets from Twitter/X using the Twitter API v2 with direct HTTP requests. It supports two main operations:
1. Fetching tweets from specific users (read from handles.json)
2. Fetching the authenticated user's home timeline

## When to Use This Skill

Use this skill when:
- You need to fetch recent tweets from specific Twitter users
- You want to retrieve the authenticated user's home timeline (posts Twitter suggests)
- You need to track tweets over time (uses per-function last run files to avoid duplicates)
- You want to export tweet data in JSON format for further processing

## Prerequisites

- Python 3.8 or higher
- Twitter Developer Account with API access
- Twitter API v2 credentials (Bearer Token and/or OAuth 1.0a credentials)
- requests library installed

## Installation

### For OpenClaw

1. Copy this skill folder to your OpenClaw skills directory:
   ```bash
   cp -r dooleys-twitter-x-reader ~/.openclaw/skills/
   ```

2. Navigate to the skill directory:
   ```bash
   cd ~/.openclaw/skills/dooleys-twitter-x-reader
   ```

3. Install Python dependencies:
   ```bash
   pip3 install -r requirements.txt
   ```

4. Set up credentials:
   ```bash
   cp config/credentials.example.json config/credentials.json
   # Edit config/credentials.json with your Twitter API credentials
   ```

5. Set up handles file (for get_users_tweets function):
   ```bash
   cp handles.json.example handles.json
   # Edit handles.json with the Twitter usernames you want to track
   ```

### For General Use

Follow the same steps above, but place the skill folder in your desired location.

## Configuration

### Credentials Setup

1. Copy the example credentials file:
   ```bash
   cp config/credentials.example.json config/credentials.json
   ```

2. Edit `config/credentials.json` and fill in your Twitter API credentials:
   ```json
   {
     "bearer_token": "YOUR_BEARER_TOKEN_HERE",
     "oauth1_consumerKey": "YOUR_CONSUMER_KEY_HERE",
     "oauth1_consumerSecret": "YOUR_CONSUMER_SECRET_HERE",
     "oauth1_accessToken": "YOUR_ACCESS_TOKEN_HERE",
     "oauth1_accessTokenSecret": "YOUR_ACCESS_TOKEN_SECRET_HERE"
   }
   ```

   **Where to get these credentials:**
   - Go to [Twitter Developer Portal](https://developer.twitter.com/en/portal/dashboard)
   - Navigate to your Project & App
   - Under "Keys and Tokens" tab:
     - Bearer Token: Generate or copy existing
     - API Key and Secret: Your Consumer Key and Secret
     - Access Token and Secret: Generate if not already created

### Handles Configuration (for get_users_tweets)

1. Copy the example handles file:
   ```bash
   cp handles.json.example handles.json
   ```

2. Edit `handles.json` with Twitter usernames (without @ symbol):
   ```json
   {
     "usernames": [
       "username1",
       "username2",
       "username3"
     ]
   }
   ```

## Instructions for AI Agent

### Function 1: get_users_tweets

**Purpose:** Fetch tweets from users listed in handles.json

**Steps:**
1. Verify that `handles.json` exists and contains usernames
2. Load credentials from `config/credentials.json`
3. Check `last_run_getUsersTweets.json` for the last execution time (if exists)
4. For each username in handles.json:
   - Build query: `from:{username}`
   - Set tweet.fields: `note_tweet,created_at,author_id,public_metrics,text,conversation_id`
   - Set expansions: `referenced_tweets.id`
   - Set max_results: 100
   - If last_run_time exists, add start_time parameter
   - Call `GET https://api.x.com/2/tweets/search/recent` with Bearer token authentication
   - Extract full text from `note_tweet.text` if available (for long-form posts)
   - Build username map from `includes.users`
   - Collect all tweets with full text, username, conversation_id, and URL
5. Group tweets by `conversation_id` in the output
6. Write grouped tweets to `output_get_users_tweets.json` (conversations object + ungrouped_tweets array)
7. Update `last_run_getUsersTweets.json` with current timestamp

**Command:**
```bash
python3 twitter.py get_users_tweets
```

**Output:**
- File: `output_get_users_tweets.json`
- Format: JSON with timestamp, total_tweets count, conversations (grouped by conversation_id), and ungrouped_tweets
- Each tweet includes: id, text (full text from note_tweet if available), created_at, author_id, username, conversation_id, public_metrics, referenced_tweets, url
- Tweets are grouped by conversation_id to show thread relationships

### Function 2: get_home_timeline

**Purpose:** Fetch the authenticated user's home timeline (posts Twitter suggests)

**Steps:**
1. Load credentials from `config/credentials.json`
2. Determine the time window using the `--post-age-within` argument (hours):
   - If provided (e.g. `--post-age-within 48`), use that many hours
   - If not provided, default to 48 hours
3. Compute `start_time` as: `now_utc - post_age_within_hours` (in RFC3339 format)
4. Set tweet.fields: `note_tweet,created_at,author_id,public_metrics,text,entities,conversation_id`
5. Set expansions: `referenced_tweets.id,author_id`
6. Set user.fields: `username,name`
7. Set max_results: 30
8. Call `GET https://api.x.com/2/users/me` with OAuth 1.0a to get the authenticated user ID
9. Call `GET https://api.x.com/2/users/{id}/timelines/reverse_chronological` with OAuth 1.0a authentication and parameters (including `start_time`)
10. For each tweet:
    - Extract full text from `note_tweet.text` if available (for long-form posts)
    - Build a map of `author_id -> username` from the `includes.users` section
    - Construct the tweet URL as `https://x.com/{username}/status/{id}`
    - Include `conversation_id` in each tweet item
11. Group tweets by `conversation_id` in the output
12. Write grouped tweets to `output_get_home_timeline.json` (conversations object + ungrouped_tweets array)

**Command:**
```bash
python3 twitter.py get_home_timeline --post-age-within 48
```

**Output:**
- File: `output_get_home_timeline.json`
- Format: JSON with timestamp, total_tweets count, conversations (grouped by conversation_id), and ungrouped_tweets
- Each tweet includes: id, text (full text from note_tweet if available), created_at, author_id, username, conversation_id, public_metrics, referenced_tweets, url
- Tweets are grouped by conversation_id to show thread relationships

## Usage Examples

### Example 1: Fetch tweets from specific users

```bash
# Ensure handles.json is configured
cat handles.json
# {
#   "usernames": ["elonmusk", "openai"]
# }

# Run the function
python3 twitter.py get_users_tweets

# Check output
cat output_get_users_tweets.json
```

### Example 2: Fetch home timeline

```bash
# Run the function
python3 twitter.py get_home_timeline

# Check output
cat output_get_home_timeline.json
```

### Example 3: Using in Python code

```python
from twitter import get_users_tweets, get_home_timeline

# Fetch user tweets
get_users_tweets()

# Fetch home timeline
get_home_timeline()
```

## Output Format

Both functions output JSON files with this structure, grouped by conversation_id:

```json
{
  "timestamp": "2024-01-27T12:00:00+00:00",
  "total_tweets": 50,
  "total_conversations": 10,
  "conversations": {
    "1234567890": {
      "conversation_id": "1234567890",
      "tweet_count": 3,
      "tweets": [
        {
          "id": "1234567890",
          "text": "Full tweet text here (extracted from note_tweet if it's a long-form post)...",
          "created_at": "2024-01-27T11:00:00+00:00",
          "author_id": "123456",
          "username": "someuser",
          "conversation_id": "1234567890",
          "url": "https://x.com/someuser/status/1234567890",
          "public_metrics": {
            "retweet_count": 10,
            "like_count": 50,
            "reply_count": 5,
            "quote_count": 2
          },
          "referenced_tweets": [
            {
              "type": "replied_to",
              "id": "0987654321"
            }
          ]
        }
      ]
    }
  },
  "ungrouped_tweets": [
    {
      "id": "9999999999",
      "text": "Tweet without conversation_id...",
      "created_at": "2024-01-27T10:00:00+00:00",
      "author_id": "789012",
      "username": "anotheruser",
      "conversation_id": null,
      "url": "https://x.com/anotheruser/status/9999999999",
      "public_metrics": {
        "retweet_count": 0,
        "like_count": 5
      }
    }
  ]
}
```

**Key Features:**
- **Full Text**: The `text` field contains the complete text, extracted from `note_tweet` for long-form posts (Twitter Notes)
- **Conversation Grouping**: Tweets with the same `conversation_id` are grouped together to show thread relationships
- **Ungrouped Tweets**: Tweets without a `conversation_id` are placed in the `ungrouped_tweets` array

## Last Run Tracking

The skill tracks the last execution time only for `get_users_tweets()`:
- `last_run_getUsersTweets.json` for `get_users_tweets()`

For `get_home_timeline()`, the time window is controlled explicitly via the `--post-age-within` argument:
- Default: 48 hours (if not provided)
- Example: `python3 twitter.py get_home_timeline --post-age-within 12` for last 12 hours.

## Error Handling

The skill handles common errors:
- Missing credentials file: Provides clear error message with setup instructions
- Missing handles.json: Creates example file and warns user
- Rate limiting: Automatically waits when rate limits are hit
- API errors: Logs errors and continues with next user (for get_users_tweets)

## Rate Limits

Twitter API v2 has rate limits:
- Search Recent Tweets: 180 requests per 15 minutes (per app)
- Get Home Timeline: 180 requests per 15 minutes (per user)

The skill implements automatic rate limit handling with exponential backoff.

## API Endpoints Used

- **get_users_tweets**: `GET https://api.x.com/2/tweets/search/recent`
  - Authentication: Bearer Token (OAuth 2.0 App-Only)
  - Parameters: query, tweet.fields, expansions, max_results, start_time

- **get_home_timeline**: `GET https://api.x.com/2/users/{id}/timelines/reverse_chronological`
  - Authentication: OAuth 1.0a User Context
  - First calls `GET https://api.x.com/2/users/me` to get authenticated user ID
  - Parameters: tweet.fields, expansions, user.fields, max_results, start_time

## Notes

- **Authentication:** 
  - `get_users_tweets()` uses Bearer Token only (simpler, read-only)
  - `get_home_timeline()` requires OAuth 1.0a (user context needed)
  
- **Tweet Fields:** The skill requests `note_tweet` field to support Twitter's new long-form tweet format (Notes)

- **Referenced Tweets:** Expansions include `referenced_tweets.id` to get information about quoted tweets, replies, etc.

- **Incremental Updates:** The `start_time` parameter ensures you only get new tweets since the last run

- **Output Files:** Output files are overwritten on each run. If you need to preserve history, implement your own backup mechanism.

## Troubleshooting

### "Credentials file not found"
- Ensure `config/credentials.json` exists
- Copy from `config/credentials.example.json` if missing

### "Missing required credentials"
- Check that all 5 credential fields are filled in `config/credentials.json`

### "No handles found"
- Ensure `handles.json` exists and contains a "usernames" array
- Copy from `handles.json.example` if missing

### Rate Limit Errors
- The skill automatically waits for rate limits
- If you see rate limit messages, wait a few minutes and try again

### Authentication Errors
- Verify your credentials are correct in `config/credentials.json`
- For OAuth 1.0a, ensure your app has the correct permissions
- Regenerate tokens if needed from Twitter Developer Portal
