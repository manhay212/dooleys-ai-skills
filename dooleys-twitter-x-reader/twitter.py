#!/usr/bin/env python3
"""
Twitter API v2 Reader Skill
Fetches tweets from Twitter/X using the Twitter API v2 via tweepy library.
"""

import json
import sys
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
import tweepy
import requests

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
                
                # Build expansions
                expansions = ['referenced_tweets.id']
                
                # Build parameters
                search_params = {
                    'query': query,
                    'tweet_fields': tweet_fields,
                    'expansions': expansions,
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
                
                if response.data:
                    tweets_data = []
                    for tweet in response.data:
                        tweet_dict = {
                            'id': tweet.id,
                            'text': tweet.text,
                            'created_at': tweet.created_at.isoformat() if tweet.created_at else None,
                            'author_id': tweet.author_id,
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
        
        function_name = 'get_home_timeline'
        last_run_time = load_last_run(function_name)
        
        # Build tweet fields
        tweet_fields = ['note_tweet', 'created_at', 'author_id', 'public_metrics', 'text']
        
        # Build expansions
        expansions = ['referenced_tweets.id']
        
        # Build parameters
        timeline_params = {
            'tweet_fields': tweet_fields,
            'expansions': expansions,
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
                    timeline_params['start_time'] = format_rfc3339(dt)
                else:
                    # Already in correct format (ends with Z)
                    timeline_params['start_time'] = last_run_time
            except Exception as e:
                logger.warning(f"Error parsing last_run_time, using as-is: {e}")
                timeline_params['start_time'] = last_run_time
            logger.info(f"Using start_time: {timeline_params['start_time']}")
        
        # Get home timeline
        logger.info("Fetching home timeline...")
        response = client.get_home_timeline(**timeline_params)
        
        tweets_data = []
        if response.data:
            for tweet in response.data:
                tweet_dict = {
                    'id': tweet.id,
                    'text': tweet.text,
                    'created_at': tweet.created_at.isoformat() if tweet.created_at else None,
                    'author_id': tweet.author_id,
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
                
                tweets_data.append(tweet_dict)
        
        # Write tweets to output file
        output_file = Path(__file__).parent / "output_get_home_timeline.json"
        output_data = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'total_tweets': len(tweets_data),
            'tweets': tweets_data
        }
        
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved {len(tweets_data)} tweets to {output_file}")
        
        # Update last run time
        save_last_run(function_name)
        
    except Exception as e:
        logger.error(f"Error in get_home_timeline(): {e}")
        raise


def main():
    """Main entry point for command-line execution."""
    if len(sys.argv) < 2:
        print("Usage: python3 twitter.py <function_name>")
        print("Available functions:")
        print("  - get_users_tweets")
        print("  - get_home_timeline")
        sys.exit(1)
    
    function_name = sys.argv[1]
    
    if function_name == "get_users_tweets":
        get_users_tweets()
    elif function_name == "get_home_timeline":
        get_home_timeline()
    else:
        print(f"Unknown function: {function_name}")
        print("Available functions: get_users_tweets, get_home_timeline")
        sys.exit(1)


if __name__ == "__main__":
    main()
