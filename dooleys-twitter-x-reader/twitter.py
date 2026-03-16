#!/usr/bin/env python3
"""
Twitter API v2 Reader Skill
Fetches tweets from Twitter/X using the Twitter API v2 via tweepy library.
"""

import json
import sys
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
import tweepy
import requests
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
CREDENTIALS_FILE = Path(__file__).parent / "config" / "credentials.json"
HANDLES_FILE = Path(__file__).parent / "handles.json"


def get_last_run_file(function_name: str) -> Path:
    """Get the last run file path for a specific function."""
    filename_map = {
        'get_users_tweets': 'last_run_getUsersTweets.json',
        'get_home_timeline': 'last_run_getHomeTimeline.json'
    }
    filename = filename_map.get(function_name, f'last_run_{function_name}.json')
    return Path(__file__).parent / filename


def load_credentials() -> Dict[str, Any]:
    """Load credentials from config/credentials.json file."""
    if not CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            f"Credentials file not found at {CREDENTIALS_FILE}. "
            "Please copy config/credentials.example.json to config/credentials.json and fill in your API keys."
        )
    
    with open(CREDENTIALS_FILE, 'r') as f:
        credentials = json.load(f)
    
    required_keys = ['bearer_token', 'oauth1_consumerKey', 'oauth1_consumerSecret', 
                    'oauth1_accessToken', 'oauth1_accessTokenSecret']
    missing_keys = [key for key in required_keys if not credentials.get(key)]
    
    if missing_keys:
        raise ValueError(f"Missing required credentials: {', '.join(missing_keys)}")
    
    return credentials


def load_handles() -> List[str]:
    """Load Twitter usernames from handles.json file."""
    if not HANDLES_FILE.exists():
        logger.warning(f"handles.json not found at {HANDLES_FILE}. Creating example file.")
        example_handles = {
            "usernames": [
                "example_user1",
                "example_user2"
            ]
        }
        with open(HANDLES_FILE, 'w') as f:
            json.dump(example_handles, f, indent=2)
        logger.info(f"Created example handles.json. Please edit it with actual usernames.")
        return []
    
    with open(HANDLES_FILE, 'r') as f:
        data = json.load(f)
    
    if 'usernames' not in data:
        raise ValueError("handles.json must contain a 'usernames' array")
    
    return data['usernames']


def load_last_run(function_name: str) -> Optional[str]:
    """Load the last run timestamp from the function-specific last run file."""
    last_run_file = get_last_run_file(function_name)
    if not last_run_file.exists():
        return None
    
    with open(last_run_file, 'r') as f:
        data = json.load(f)
    
    return data.get('last_run_time')


def format_rfc3339(dt: datetime) -> str:
    """
    Format datetime to RFC3339 format required by Twitter API.
    Format: yyyy-MM-dd'T'HH:mm:ss[.SSS]Z
    Twitter requires: yyyy-MM-dd'T'HH:mm:ss[.SSS]X where X is timezone (Z or +00:00)
    We use Z for UTC to match Twitter's preferred format.
    """
    # Ensure timezone-aware datetime (UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    elif dt.tzinfo != timezone.utc:
        dt = dt.astimezone(timezone.utc)
    
    # Format with milliseconds (3 digits) and Z for UTC
    # strftime %f gives microseconds (6 digits), we take first 3 for milliseconds
    formatted = dt.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
    return formatted


def save_last_run(function_name: str) -> None:
    """Save the current timestamp to the function-specific last run file."""
    current_time = format_rfc3339(datetime.now(timezone.utc))
    data = {'last_run_time': current_time}
    
    last_run_file = get_last_run_file(function_name)
    with open(last_run_file, 'w') as f:
        json.dump(data, f, indent=2)
    
    logger.info(f"Saved last run time for {function_name}: {current_time}")


def get_users_tweets() -> None:
    """
    Fetch tweets from users listed in handles.json.
    Uses bearer token authentication and Twitter API v2 search endpoint.
    """
    logger.info("Starting get_users_tweets() function")
    
    try:
        credentials = load_credentials()
        bearer_token = credentials['bearer_token']
        
        if not bearer_token:
            raise ValueError("bearer_token is required in credentials.json")
        
        handles = load_handles()
        if not handles:
            logger.warning("No handles found in handles.json. Exiting.")
            return
        
        function_name = 'get_users_tweets'
        last_run_time = load_last_run(function_name)
        
        # Initialize tweepy client with bearer token only
        client = tweepy.Client(bearer_token=bearer_token, wait_on_rate_limit=True)
        
        all_tweets = []
        
        for username in handles:
            logger.info(f"Fetching tweets for user: {username}")
            
            try:
                # Build query with from:username
                query = f"from:{username}"
                
                # Build tweet fields
                tweet_fields = ['note_tweet', 'created_at', 'author_id', 'public_metrics', 'text']
                
                # Build expansions (include author_id so we can map to usernames)
                expansions = ['referenced_tweets.id', 'author_id']

                # Build user fields (to get the username/handle)
                user_fields = ['username', 'name']
                
                # Build parameters
                search_params = {
                    'query': query,
                    'tweet_fields': tweet_fields,
                    'expansions': expansions,
                    'user_fields': user_fields,
                    'max_results': 100
                }
                
                # Add start_time if last_run exists
                if last_run_time:
                    # Ensure start_time is in RFC3339 format
                    # If it's already in the correct format, use it; otherwise parse and reformat
                    try:
                        # Try to parse the stored time and reformat to ensure RFC3339 compliance
                        if '+' in last_run_time or last_run_time.endswith('+00:00'):
                            # Parse and reformat to RFC3339 with Z
                            dt = datetime.fromisoformat(last_run_time.replace('Z', '+00:00'))
                            search_params['start_time'] = format_rfc3339(dt)
                        else:
                            # Already in correct format (ends with Z)
                            search_params['start_time'] = last_run_time
                    except Exception as e:
                        logger.warning(f"Error parsing last_run_time, using as-is: {e}")
                        search_params['start_time'] = last_run_time
                    logger.info(f"Using start_time: {search_params['start_time']}")
                
                # Search for tweets
                response = client.search_recent_tweets(**search_params)

                # Build a map of author_id -> username from includes.users
                user_map: Dict[str, Optional[str]] = {}
                try:
                    includes = getattr(response, 'includes', None)
                    if includes and 'users' in includes:
                        for user in includes['users']:
                            user_id = getattr(user, 'id', None)
                            uname = getattr(user, 'username', None)
                            if user_id:
                                user_map[str(user_id)] = uname
                except Exception as e:
                    logger.warning(f"Error building user map from includes for {username}: {e}")
                
                if response.data:
                    tweets_data = []
                    for tweet in response.data:
                        author_id = tweet.author_id
                        uname = user_map.get(str(author_id)) if author_id is not None else None

                        tweet_dict = {
                            'id': tweet.id,
                            'text': tweet.text,
                            'created_at': tweet.created_at.isoformat() if tweet.created_at else None,
                            'author_id': author_id,
                            'username': uname,
                        }
                        
                        # Add public_metrics if available
                        if hasattr(tweet, 'public_metrics') and tweet.public_metrics:
                            tweet_dict['public_metrics'] = tweet.public_metrics
                        
                        # Add referenced tweets if available
                        if hasattr(tweet, 'referenced_tweets') and tweet.referenced_tweets:
                            tweet_dict['referenced_tweets'] = [
                                {'type': ref.type, 'id': ref.id} 
                                for ref in tweet.referenced_tweets
                            ]

                        # Construct tweet URL if we have a username
                        if uname:
                            tweet_dict['url'] = f"https://x.com/{uname}/status/{tweet.id}"
                        else:
                            tweet_dict['url'] = None
                        
                        tweets_data.append(tweet_dict)
                    
                    all_tweets.extend(tweets_data)
                    logger.info(f"Found {len(tweets_data)} tweets for {username}")
                else:
                    logger.info(f"No tweets found for {username}")
                    
            except tweepy.TooManyRequests:
                logger.error(f"Rate limit exceeded for {username}. Waiting...")
                # tweepy will handle rate limiting automatically with wait_on_rate_limit=True
                continue
            except Exception as e:
                logger.error(f"Error fetching tweets for {username}: {e}")
                continue
        
        # Write all tweets to output file
        output_file = Path(__file__).parent / "output_get_users_tweets.json"
        output_data = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'total_tweets': len(all_tweets),
            'tweets': all_tweets
        }
        
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved {len(all_tweets)} tweets to {output_file}")
        
        # Update last run time
        save_last_run(function_name)
        
    except Exception as e:
        logger.error(f"Error in get_users_tweets(): {e}")
        raise


def get_home_timeline() -> None:
    """
    Fetch the authenticated user's home timeline (posts Twitter suggests).
    Uses OAuth 1.0a authentication.
    """
    logger.info("Starting get_home_timeline() function")
    
    try:
        credentials = load_credentials()
        
        # Initialize tweepy client with OAuth 1.0a credentials
        client = tweepy.Client(
            consumer_key=credentials['oauth1_consumerKey'],
            consumer_secret=credentials['oauth1_consumerSecret'],
            access_token=credentials['oauth1_accessToken'],
            access_token_secret=credentials['oauth1_accessTokenSecret'],
            wait_on_rate_limit=True
        )
        
        # Build tweet fields
        # NOTE: Do NOT request organic_metrics here; it requires elevated permissions and
        # causes "not authorized for field" errors on many accounts.
        tweet_fields = ['note_tweet', 'created_at', 'author_id', 'public_metrics', 'text', 'entities']
        
        # Build expansions (include author_id so we can get usernames)
        expansions = ['referenced_tweets.id', 'author_id']

        # Build user fields (to get the username/handle)
        user_fields = ['username', 'name']
        
        # Build parameters
        timeline_params = {
            'tweet_fields': tweet_fields,
            'expansions': expansions,
            'user_fields': user_fields,
            'max_results': 30,
            # Be explicit: home timeline requires user context
            'user_auth': True,
        }
        
        # Compute start_time based on "post-age-within" hours (CLI arg parsing done in main())
        # Default to 48 hours if not provided.
        hours_within_env = os.environ.get("HOME_TIMELINE_POST_AGE_WITHIN_HOURS")  # set by main()
        try:
            hours_within = int(hours_within_env) if hours_within_env is not None else 48
        except ValueError:
            logger.warning(f"Invalid HOME_TIMELINE_POST_AGE_WITHIN_HOURS='{hours_within_env}', defaulting to 48 hours")
            hours_within = 48

        now_utc = datetime.now(timezone.utc)
        start_dt = now_utc - timedelta(hours=hours_within)
        start_time_str = format_rfc3339(start_dt)
        timeline_params['start_time'] = start_time_str
        logger.info(f"Using start_time (now - {hours_within}h): {start_time_str}")

        # Get home timeline
        logger.info("Fetching home timeline...")
        response = client.get_home_timeline(**timeline_params)

        # Build a map of author_id -> username from includes.users
        user_map: Dict[str, Optional[str]] = {}
        try:
            includes = getattr(response, 'includes', None)
            if includes and 'users' in includes:
                for user in includes['users']:
                    user_id = getattr(user, 'id', None)
                    username = getattr(user, 'username', None)
                    if user_id:
                        user_map[str(user_id)] = username
        except Exception as e:
            logger.warning(f"Error building user map from includes: {e}")
        
        tweets_data = []
        if response.data:
            for tweet in response.data:
                author_id = tweet.author_id
                username = user_map.get(str(author_id)) if author_id is not None else None

                tweet_dict = {
                    'id': tweet.id,
                    'text': tweet.text,
                    'created_at': tweet.created_at.isoformat() if tweet.created_at else None,
                    'author_id': author_id,
                    'username': username,
                }
                
                # Add public_metrics if available
                if hasattr(tweet, 'public_metrics') and tweet.public_metrics:
                    tweet_dict['public_metrics'] = tweet.public_metrics
                
                # Add referenced tweets if available
                if hasattr(tweet, 'referenced_tweets') and tweet.referenced_tweets:
                    tweet_dict['referenced_tweets'] = [
                        {'type': ref.type, 'id': ref.id} 
                        for ref in tweet.referenced_tweets
                    ]

                # Construct tweet URL if we have a username
                if username:
                    tweet_dict['url'] = f"https://x.com/{username}/status/{tweet.id}"
                else:
                    tweet_dict['url'] = None
                
                tweets_data.append(tweet_dict)
        
        # Write tweets to output file
        output_file = Path(__file__).parent / "output_get_home_timeline.json"
        output_data = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'total_tweets': len(tweets_data),
            'tweets': tweets_data,
        }
        
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved {len(tweets_data)} tweets to {output_file}")
        
    except Exception as e:
        logger.error(f"Error in get_home_timeline(): {e}")
        raise


def main():
    """Main entry point for command-line execution."""
    if len(sys.argv) < 2:
        print("Usage: python3 twitter.py <function_name> [options]")
        print("Available functions:")
        print("  - get_users_tweets")
        print("  - get_home_timeline [--post-age-within HOURS]")
        sys.exit(1)
    
    function_name = sys.argv[1]

    # Simple manual arg parsing to avoid adding dependencies
    args = sys.argv[2:]
    
    if function_name == "get_users_tweets":
        get_users_tweets()
    elif function_name == "get_home_timeline":
        # Default post-age-within to 48 hours
        post_age_within_hours = 48
        if "--post-age-within" in args:
            idx = args.index("--post-age-within")
            if idx + 1 < len(args):
                try:
                    post_age_within_hours = int(args[idx + 1])
                except ValueError:
                    print(f"Invalid value for --post-age-within: {args[idx + 1]}. Using default 48 hours.")
            else:
                print("Missing value for --post-age-within. Using default 48 hours.")
        # Pass value to get_home_timeline via environment (to avoid changing its signature)
        os.environ["HOME_TIMELINE_POST_AGE_WITHIN_HOURS"] = str(post_age_within_hours)
        get_home_timeline()
    else:
        print(f"Unknown function: {function_name}")
        print("Available functions: get_users_tweets, get_home_timeline [--post-age-within HOURS]")
        sys.exit(1)


if __name__ == "__main__":
    main()


# tweet_fields values and descriptions:

# Core Metadata Fields
# created_at: The date and time when the tweet was created (UTC).
# author_id: The unique user ID of the person who posted the tweet.
# conversation_id: The ID of the original tweet that started the conversation/thread, helpful for grouping replies.
# lang: The BCP 47 language code of the tweet text (e.g., "en" for English).
# source: The name of the application used to send the tweet (e.g., "Twitter for iPhone").
# possibly_sensitive: A boolean value indicating if the tweet content is flagged as sensitive by Twitter.
# withheld: Contains details if the content is withheld in certain countries due to legal restrictions. 

# Engagement and Performance Fields
# public_metrics: Returns engagement counts at the time of the request, including retweet_count, reply_count, like_count, and quote_count.
# non_public_metrics: (Available for authenticated users, last 30 days) Private metrics such as URL clicks or detail expands.
# organic_metrics: Metrics for organic (non-promoted) tweets.
# promoted_metrics: Metrics for tweets that were promoted (requires user context authentication). 

# Content and Structure Fields
# attachments: Contains keys for media (images/videos) or polls attached to the tweet. Requires expansions to get full media/poll details.
# entities: Returns detailed metadata within the text, including hashtags, mentions, URLs, and cashtags.
# referenced_tweets: A list of tweets that this tweet refers to, such as replied_to or retweeted.
# reply_settings: Defines who can reply to the tweet ("everyone", "mentioned_users", or "followers").
# geo: Contains geolocation details if the user tagged a location, including place ID or coordinates.
# note_tweet: Used for long-form tweets, providing the extended text content. 

# Edit & Context Fields
# edit_controls: Information about whether the tweet is eligible for editing, how much time is left, and how many edits remain.
# context_annotations: Information about the topics and entities (e.g., politicians, sports teams) derived by Twitter’s AI to provide context to the tweet. 



# Expansions:

# Available Expansions for Tweets:
# author_id: Returns the user object of the Tweet’s author.
# referenced_tweets.id: Returns the full Tweet object for any Retweet, Quote, or Reply referenced.
# attachments.media_keys: Returns media objects (images, videos, GIFs) attached to the Tweet.
# attachments.poll_ids: Returns the full poll object if the Tweet has a poll.
# geo.place_id: Returns a "Place" object with location details.
# entities.mentions.username: Returns user objects for everyone mentioned in the Tweet. 



# user.fields:
# username