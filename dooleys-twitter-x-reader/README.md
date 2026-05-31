# dooleys-twitter-x-reader

A Python skill for fetching tweets from Twitter/X using direct HTTP requests to the Twitter API v2. This skill provides two main functions:
1. Fetch tweets from specific users (read from `handles.json`)
2. Fetch the authenticated user's home timeline

## Features

- ✅ Twitter API v2 integration using direct HTTP requests (no library dependencies)
- ✅ Environment variable support for AI agent integration
- ✅ Config file fallback for standalone use
- ✅ Bearer token authentication for user tweet fetching
- ✅ OAuth 1.0a authentication for home timeline
- ✅ Automatic last-run tracking to avoid duplicates
- ✅ Full support for note_tweet fields (Twitter's long-form content)
- ✅ Referenced tweets expansion
- ✅ Automatic rate limit handling with exponential backoff
- ✅ JSON output format

## Installation

### Prerequisites

- Python 3.8 or higher
- Twitter Developer Account
- Twitter API v2 access

### Step 1: Install Dependencies

```bash
pip3 install -r requirements.txt
```

Only `requests` library is required.

### Step 2: Set Up Credentials

**Option A: Environment Variables (Recommended for AI Agents)**

Set these environment variables — the skill checks them first:

```bash
export TWITTER_BEARER_TOKEN=your_bearer_token
export TWITTER_OAUTH_CONSUMER_KEY=your_consumer_key
export TWITTER_OAUTH_CONSUMER_SECRET=your_consumer_secret
export TWITTER_OAUTH_ACCESS_TOKEN=your_access_token
export TWITTER_OAUTH_ACCESS_TOKEN_SECRET=your_access_token_secret
```

For Hermes Agent, add these to `~/.hermes/.env` and run `/reload` in chat.

**Option B: Config File (Standalone Use)**

1. Copy the example credentials file:
   ```bash
   cp config/credentials.example.json config/credentials.json
   ```

2. Edit `config/credentials.json` with your Twitter API credentials:
   ```json
   {
     "bearer_token": "YOUR_BEARER_TOKEN",
     "oauth1_consumerKey": "YOUR_CONSUMER_KEY",
     "oauth1_consumerSecret": "YOUR_CONSUMER_SECRET",
     "oauth1_accessToken": "YOUR_ACCESS_TOKEN",
     "oauth1_accessTokenSecret": "YOUR_ACCESS_TOKEN_SECRET"
   }
   ```

**Getting Your Credentials (both methods):**
   - Visit [Twitter Developer Portal](https://developer.twitter.com/en/portal/dashboard)
   - Navigate to your Project & App
   - Go to "Keys and Tokens" tab
   - Copy the Bearer Token, API Key/Secret, and Access Token/Secret

### Step 3: Configure Handles (Optional)

For the `get_users_tweets` function, set up the usernames you want to track:

```bash
cp handles.json.example handles.json
```

Edit `handles.json`:
```json
{
  "usernames": [
    "username1",
    "username2",
    "username3"
  ]
}
```

**Note:** Do not include the `@` symbol in usernames.

## Usage

### Command Line

#### Fetch Tweets from Users

```bash
python3 twitter.py get_users_tweets
```

This will:
- Read usernames from `handles.json`
- Fetch recent tweets from each user
- Save results to `output_get_users_tweets.json`
- Update `last_run_getUsersTweets.json` with execution timestamp

#### Fetch Home Timeline

```bash
python3 twitter.py get_home_timeline --post-age-within 48
```

This will:
- Fetch your home timeline (posts Twitter suggests)
- Save results to `output_get_home_timeline.json`
- Fetch tweets from approximately the last 48 hours (default window, configurable)

### Python Import

```python
from twitter import get_users_tweets, get_home_timeline

# Fetch user tweets
get_users_tweets()

# Fetch home timeline
get_home_timeline()
```

## Output Format

Both functions generate JSON files grouped by conversation_id with the following structure:

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
          "text": "Full tweet text (extracted from note_tweet for long-form posts)...",
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
- **Full Text**: The `text` field contains complete text, automatically extracted from `note_tweet` for long-form posts (Twitter Notes)
- **Conversation Grouping**: Tweets sharing the same `conversation_id` are grouped together to show thread relationships
- **Ungrouped Tweets**: Tweets without a `conversation_id` appear in the `ungrouped_tweets` array

## Last Run Tracking

The skill automatically tracks execution time only for `get_users_tweets()`:
- `last_run_getUsersTweets.json` for `get_users_tweets()`

For `get_home_timeline()`, the time window is controlled explicitly via the `--post-age-within` option:
- Default: 48 hours (if not provided)
- Example: `python3 twitter.py get_home_timeline --post-age-within 24` fetches tweets from roughly the last 24 hours.

## File Structure

```
dooleys-twitter-x-reader/
├── twitter.py                      # Main script
├── SKILL.md                        # Skill documentation for AI agents
├── README.md                       # This file
├── requirements.txt                # Python dependencies
├── .gitignore                      # Git ignore rules
├── config/
│   ├── credentials.example.json   # Credentials template
│   └── credentials.json            # Your credentials (not in git)
├── handles.json                    # Usernames to track (create from example)
├── handles.json.example            # Example handles file
├── last_run_getUsersTweets.json    # Last execution timestamp for get_users_tweets (auto-generated)
├── output_get_users_tweets.json   # Output from get_users_tweets (auto-generated)
└── output_get_home_timeline.json  # Output from get_home_timeline (auto-generated)
```

## Authentication Methods

### Bearer Token (get_users_tweets)
- Simpler authentication
- Read-only access
- Sufficient for fetching public tweets
- Uses OAuth 2.0 Bearer Token

### OAuth 1.0a (get_home_timeline)
- User context required
- Needed for accessing home timeline
- Requires all 4 OAuth credentials
- Implements proper OAuth 1.0a signature generation

## API Parameters

Both functions use these Twitter API v2 parameters:

- **tweet.fields**: `note_tweet,created_at,author_id,public_metrics,text,conversation_id` (and `entities` for home timeline)
- **expansions**: `referenced_tweets.id` (and `author_id` for home timeline)
- **user.fields**: `username,name` (home timeline only)
- **max_results**: `100` for `get_users_tweets`, `30` for `get_home_timeline`
- **start_time**:
  - For `get_users_tweets`: automatically added from `last_run_getUsersTweets.json` if available
  - For `get_home_timeline`: computed from `--post-age-within` hours (default 48 if not provided)

## API Endpoints

- **get_users_tweets**: `GET https://api.x.com/2/tweets/search/recent`
  - Authentication: Bearer Token
  - Parameters: query, tweet.fields, expansions, max_results, start_time

- **get_home_timeline**: `GET https://api.x.com/2/users/{id}/timelines/reverse_chronological`
  - Authentication: OAuth 1.0a User Context
  - First calls `GET https://api.x.com/2/users/me` to get authenticated user ID
  - Parameters: tweet.fields, expansions, user.fields, max_results, start_time

## Rate Limits

Twitter API v2 rate limits:
- **Search Recent Tweets**: 180 requests per 15-minute window (per app)
- **Get Home Timeline**: 180 requests per 15-minute window (per user)

The skill implements automatic rate limit handling with exponential backoff.

## Troubleshooting

### Credentials Not Found
```
FileNotFoundError: Credentials file not found at...
```
**Solution:** Copy `config/credentials.example.json` to `config/credentials.json` and fill in your credentials.

### Missing Credentials
```
ValueError: Missing required credentials: bearer_token
```
**Solution:** Ensure all 5 credential fields are filled in `config/credentials.json`.

### No Handles Found
```
No handles found in handles.json. Exiting.
```
**Solution:** Create `handles.json` from `handles.json.example` and add usernames.

### Rate Limit Errors
The skill automatically waits for rate limits. If you see rate limit messages, wait a few minutes before running again.

### Authentication Errors
- Verify credentials are correct
- Check that your Twitter app has the necessary permissions
- Regenerate tokens from Twitter Developer Portal if needed
- For OAuth 1.0a errors, ensure all 4 OAuth credentials are correct

## Dependencies

- **requests** (>=2.31.0): HTTP library for making API calls

## Security Notes

- **Never commit `config/credentials.json`** - It's in `.gitignore`
- Keep your API keys secure
- Do not share credentials publicly
- Rotate tokens if compromised

## License

This skill is part of the Custom Skills project. Use at your own risk.

## Support

For issues or questions:
1. Check the troubleshooting section
2. Review Twitter API v2 documentation
3. Check the code comments for implementation details

## Changelog

### Version 1.0.0
- Initial release
- Direct HTTP requests (no tweepy dependency)
- Support for get_users_tweets and get_home_timeline
- OAuth 1.0a signature implementation
- Last run tracking
- JSON output format
