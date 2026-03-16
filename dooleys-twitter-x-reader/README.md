# dooleys-twitter-x-reader

A Python skill for fetching tweets from Twitter/X using the Twitter API v2. This skill provides two main functions:
1. Fetch tweets from specific users (read from `handles.json`)
2. Fetch the authenticated user's home timeline

## Features

- ✅ Twitter API v2 integration using tweepy
- ✅ Bearer token authentication for user tweet fetching
- ✅ OAuth 1.0a authentication for home timeline
- ✅ Automatic last-run tracking to avoid duplicates
- ✅ Support for note_tweet fields (Twitter's long-form content)
- ✅ Referenced tweets expansion
- ✅ Rate limit handling
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

### Step 2: Set Up Credentials

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

   **Getting Your Credentials:**
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
python3 twitter.py get_home_timeline
```

This will:
- Fetch your home timeline (posts Twitter suggests)
- Save results to `output_get_home_timeline.json`
- Update `last_run_getHomeTimeline.json` with execution timestamp

### Python Import

```python
from twitter import get_users_tweets, get_home_timeline

# Fetch user tweets
get_users_tweets()

# Fetch home timeline
get_home_timeline()
```

## Output Format

Both functions generate JSON files with the following structure:

```json
{
  "timestamp": "2024-01-27T12:00:00+00:00",
  "total_tweets": 50,
  "tweets": [
    {
      "id": "1234567890",
      "text": "Tweet content...",
      "created_at": "2024-01-27T11:00:00+00:00",
      "author_id": "123456",
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

The skill automatically tracks execution time separately for each function:
- `last_run_getUsersTweets.json` for `get_users_tweets()`
- `last_run_getHomeTimeline.json` for `get_home_timeline()`

This ensures:
- Only new tweets are fetched on subsequent runs of each function
- Avoids duplicate data per function
- Enables independent incremental updates

The `start_time` parameter is automatically added to API calls if the corresponding last run file exists.

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
├── last_run_getHomeTimeline.json   # Last execution timestamp for get_home_timeline (auto-generated)
├── output_get_users_tweets.json   # Output from get_users_tweets (auto-generated)
└── output_get_home_timeline.json  # Output from get_home_timeline (auto-generated)
```

## Authentication Methods

### Bearer Token (get_users_tweets)
- Simpler authentication
- Read-only access
- Sufficient for fetching public tweets

### OAuth 1.0a (get_home_timeline)
- User context required
- Needed for accessing home timeline
- Requires all 4 OAuth credentials

## API Parameters

Both functions use these Twitter API v2 parameters:

- **tweet.fields**: `note_tweet` - Supports Twitter's long-form content
- **expansions**: `referenced_tweets.id` - Includes quoted tweets, replies
- **max_results**: `100` - Maximum tweets per request
- **start_time**: Automatically added from the corresponding last run file if available

## Rate Limits

Twitter API v2 rate limits:
- **Search Recent Tweets**: 180 requests per 15 minutes (per app)
- **Get Home Timeline**: 15 requests per 15 minutes (per user)

The skill automatically handles rate limits using `wait_on_rate_limit=True`.

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

## Dependencies

- **tweepy** (>=4.14.0): Twitter API v2 client library
- **requests** (>=2.31.0): HTTP library (used by tweepy)

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
3. Check tweepy documentation: https://docs.tweepy.org/

## Changelog

### Version 1.0.0
- Initial release
- Support for get_users_tweets and get_home_timeline
- Last run tracking
- JSON output format
