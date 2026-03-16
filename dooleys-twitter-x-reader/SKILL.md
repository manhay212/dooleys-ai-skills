---
name: dooleys-twitter-x-reader
description: Fetch tweets from Twitter/X API v2. Use this skill when you need to retrieve user tweets or home timeline from Twitter. Supports fetching tweets from specific users listed in handles.json or getting the authenticated user's home timeline feed.
version: 1.0.0
---

# Twitter/X Reader Skill

This skill provides functionality to fetch tweets from Twitter/X using the Twitter API v2. It supports two main operations:
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
- tweepy library installed

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
   - Initialize tweepy Client with bearer_token only
   - Build query: `from:{username}`
   - Set tweet_fields: `['note_tweet', 'created_at', 'author_id', 'public_metrics', 'text']`
   - Set expansions: `['referenced_tweets.id']`
   - Set max_results: 100
   - If last_run_time exists, add start_time parameter
   - Call `client.search_recent_tweets()` with the parameters
   - Collect all tweets
5. Write all collected tweets to `output_get_users_tweets.json`
6. Update `last_run_getUsersTweets.json` with current timestamp

**Command:**
```bash
python3 twitter.py get_users_tweets
```

**Output:**
- File: `output_get_users_tweets.json`
- Format: JSON with timestamp, total_tweets count, and tweets array
- Each tweet includes: id, text, created_at, author_id, username, public_metrics, referenced_tweets, url

### Function 2: get_home_timeline

**Purpose:** Fetch the authenticated user's home timeline (posts Twitter suggests)

**Steps:**
1. Load credentials from `config/credentials.json`
2. Initialize tweepy Client with OAuth 1.0a credentials:
   - consumer_key (oauth1_consumerKey)
   - consumer_secret (oauth1_consumerSecret)
   - access_token (oauth1_accessToken)
   - access_token_secret (oauth1_accessTokenSecret)
3. Determine the time window using the `--post-age-within` argument (hours):
   - If provided (e.g. `--post-age-within 48`), use that many hours
   - If not provided, default to 48 hours
4. Compute `start_time` as: `now_utc - post_age_within_hours` (in RFC3339 format)
5. Set tweet_fields: `['note_tweet', 'created_at', 'author_id', 'public_metrics', 'text']`
6. Set expansions: `['referenced_tweets.id', 'author_id']`
7. Set user_fields: `['username', 'name']`
8. Set max_results: 30
9. Call `client.get_home_timeline()` with the parameters (including `start_time`)
10. For each tweet, build a map of `author_id -> username` from the `includes.users` section
11. Construct the tweet URL as `https://x.com/{username}/status/{id}` and add it to each tweet item
12. Write tweets to `output_get_home_timeline.json`

**Command:**
```bash
python3 twitter.py get_home_timeline --post-age-within 48
```

**Output:**
- File: `output_get_home_timeline.json`
- Format: JSON with timestamp, total_tweets count, and tweets array
- Each tweet includes: id, text, created_at, author_id, username, public_metrics, referenced_tweets, url

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

Both functions output JSON files with this structure:

```json
{
  "timestamp": "2024-01-27T12:00:00+00:00",
  "total_tweets": 50,
  "tweets": [
    {
      "id": "1234567890",
      "text": "Tweet content here...",
      "created_at": "2024-01-27T11:00:00+00:00",
      "author_id": "123456",
      "username": "someuser",
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
```

## Last Run Tracking

The skill tracks the last execution time only for `get_users_tweets()`:
- `last_run_getUsersTweets.json` for `get_users_tweets()`

For `get_home_timeline()`, the time window is controlled explicitly via the `--post-age-within` argument:
- Default: 48 hours (last 2 days)
- You can override this per run (e.g. `--post-age-within 12` for last 12 hours).

## Error Handling

The skill handles common errors:
- Missing credentials file: Provides clear error message with setup instructions
- Missing handles.json: Creates example file and warns user
- Rate limiting: Automatically waits when rate limits are hit (tweepy handles this)
- API errors: Logs errors and continues with next user (for get_users_tweets)

## Rate Limits

Twitter API v2 has rate limits:
- Search Recent Tweets: 180 requests per 15 minutes (per app)
- Get Home Timeline: 15 requests per 15 minutes (per user)

The skill uses `wait_on_rate_limit=True` to automatically handle rate limits.

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
