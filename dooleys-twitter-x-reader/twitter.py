#!/usr/bin/env python3
"""
Twitter API v2 Reader Skill
Fetches tweets from Twitter/X using direct HTTP requests to Twitter API v2.
"""

import json
import sys
import logging
import time
import hmac
import hashlib
import base64
import urllib.parse
import uuid
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
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
BASE_URL = "https://api.x.com/2"


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
    """
    # Ensure timezone-aware datetime (UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    elif dt.tzinfo != timezone.utc:
        dt = dt.astimezone(timezone.utc)
    
    # Format with milliseconds (3 digits) and Z for UTC
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


def generate_oauth1_header(url: str, method: str, credentials: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None) -> str:
    """
    Generate OAuth 1.0a authorization header.
    
    Args:
        url: The full URL of the request
        method: HTTP method (GET, POST, etc.)
        credentials: Dict containing oauth1 credentials
        params: Optional query parameters
    
    Returns:
        Authorization header string
    """
    oauth_params = {
        'oauth_consumer_key': credentials['oauth1_consumerKey'],
        'oauth_nonce': uuid.uuid4().hex,
        'oauth_signature_method': 'HMAC-SHA1',
        'oauth_timestamp': str(int(time.time())),
        'oauth_token': credentials['oauth1_accessToken'],
        'oauth_version': '1.0'
    }
    
    # Combine all parameters for signature
    all_params = oauth_params.copy()
    if params:
        all_params.update(params)
    
    # Create parameter string
    encoded_params = []
    for key in sorted(all_params.keys()):
        value = all_params[key]
        if isinstance(value, list):
            # Handle list parameters (like tweet.fields)
            value = ','.join(value)
        encoded_params.append(f"{urllib.parse.quote(str(key), safe='')}=\"{urllib.parse.quote(str(value), safe='')}\"")
    
    # Create base string
    base_url = url.split('?')[0]  # Remove query string
    param_string = '&'.join([f"{urllib.parse.quote(str(k), safe='')}={urllib.parse.quote(str(all_params[k]), safe='')}" 
                            for k in sorted(all_params.keys())])
    base_string = f"{method.upper()}&{urllib.parse.quote(base_url, safe='')}&{urllib.parse.quote(param_string, safe='')}"
    
    # Create signing key
    signing_key = f"{urllib.parse.quote(credentials['oauth1_consumerSecret'], safe='')}&{urllib.parse.quote(credentials['oauth1_accessTokenSecret'], safe='')}"
    
    # Generate signature
    signature = hmac.new(
        signing_key.encode('utf-8'),
        base_string.encode('utf-8'),
        hashlib.sha1
    ).digest()
    oauth_params['oauth_signature'] = base64.b64encode(signature).decode('utf-8')
    
    # Build header
    auth_header = 'OAuth ' + ', '.join(
        [
            f'{k}="{urllib.parse.quote(str(oauth_params[k]), safe="")}"'
            for k in [
                'oauth_consumer_key',
                'oauth_nonce',
                'oauth_signature',
                'oauth_signature_method',
                'oauth_timestamp',
                'oauth_token',
                'oauth_version',
            ]
        ]
    )
    
    return auth_header


def make_api_request(url: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None,
                     max_retries: int = 3) -> Dict[str, Any]:
    """
    Make API request with rate limit handling and retries.
    
    Args:
        url: API endpoint URL
        headers: Request headers
        params: Query parameters
        max_retries: Maximum number of retries for rate limiting
    
    Returns:
        JSON response as dict
    """
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            # Handle rate limiting
            if response.status_code == 429:
                reset_time = int(response.headers.get('x-rate-limit-reset', 0))
                if reset_time:
                    wait_time = max(0, reset_time - int(time.time())) + 5
                    logger.warning(f"Rate limit hit. Waiting {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                else:
                    wait_time = 60 * (attempt + 1)
                    logger.warning(f"Rate limit hit. Waiting {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed (attempt {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                raise
    
    raise Exception("Max retries exceeded")


def build_tweet_dict(tweet: Dict[str, Any], user_map: Optional[Dict[str, Optional[str]]] = None) -> Dict[str, Any]:
    """
    Build a standardized tweet dictionary from API response.
    
    Args:
        tweet: Raw tweet data from API
        user_map: Optional mapping of author_id to username
    
    Returns:
        Standardized tweet dictionary
    """
    tweet_id = tweet.get('id')
    author_id = tweet.get('author_id')
    username = user_map.get(str(author_id)) if user_map and author_id else None
    
    # Extract full text from note_tweet if available (for long-form posts)
    full_text = tweet.get('text', '')
    note_tweet_obj = tweet.get('note_tweet')
    note_tweet_text = None
    if note_tweet_obj and isinstance(note_tweet_obj, dict):
        note_tweet_text = note_tweet_obj.get('text')
        if note_tweet_text:
            full_text = note_tweet_text
    
    tweet_dict = {
        'id': tweet_id,
        'text': full_text,
        'created_at': tweet.get('created_at'),
        'author_id': author_id,
        'username': username,
        'conversation_id': tweet.get('conversation_id'),
    }
    
    # Preserve note_tweet content explicitly for downstream use
    if note_tweet_obj:
        tweet_dict['note_tweet'] = {
            'text': note_tweet_text or ''
        }
    
    # Add public_metrics if available
    if 'public_metrics' in tweet:
        tweet_dict['public_metrics'] = tweet['public_metrics']
    
    # Add referenced tweets if available
    if 'referenced_tweets' in tweet and tweet['referenced_tweets']:
        tweet_dict['referenced_tweets'] = [
            {'type': ref.get('type'), 'id': ref.get('id')} 
            for ref in tweet['referenced_tweets']
        ]
    
    # Construct tweet URL if we have a username
    if username:
        tweet_dict['url'] = f"https://x.com/{username}/status/{tweet_id}"
    else:
        tweet_dict['url'] = None
    
    return tweet_dict


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
        
        all_tweets = []
        
        for username in handles:
            logger.info(f"Fetching tweets for user: {username}")
            
            try:
                # Build query parameters
                params = {
                    'query': f"from:{username}",
                    'tweet.fields': ','.join(
                        ['note_tweet', 'created_at', 'author_id', 'public_metrics', 'text', 'conversation_id']
                    ),
                    # Need author_id expansion + user.fields to resolve usernames for URL construction
                    'expansions': 'referenced_tweets.id,author_id',
                    'user.fields': 'username,name',
                    'max_results': 100,
                }
                
                # Add start_time if last_run exists
                if last_run_time:
                    params['start_time'] = last_run_time
                    logger.info(f"Using start_time: {last_run_time}")
                
                # Make API request with Bearer token
                headers = {
                    'Authorization': f'Bearer {bearer_token}',
                    'Content-Type': 'application/json'
                }
                
                response_data = make_api_request(
                    f"{BASE_URL}/tweets/search/recent",
                    headers,
                    params
                )
                
                # Build user map from includes.users
                user_map: Dict[str, Optional[str]] = {}
                includes = response_data.get('includes', {})
                if 'users' in includes:
                    for user in includes['users']:
                        user_id = user.get('id')
                        uname = user.get('username')
                        if user_id:
                            user_map[str(user_id)] = uname
                
                # Process tweets
                if 'data' in response_data:
                    for tweet in response_data['data']:
                        tweet_dict = build_tweet_dict(tweet, user_map)
                        all_tweets.append(tweet_dict)
                    
                    logger.info(f"Found {len(response_data['data'])} tweets for {username}")
                else:
                    logger.info(f"No tweets found for {username}")
                    
            except Exception as e:
                logger.error(f"Error fetching tweets for {username}: {e}")
                continue
        
        # Group tweets by conversation_id
        conversations: Dict[str, List[Dict[str, Any]]] = {}
        ungrouped_tweets: List[Dict[str, Any]] = []
        
        for tweet in all_tweets:
            conv_id = tweet.get('conversation_id')
            if conv_id:
                if conv_id not in conversations:
                    conversations[conv_id] = []
                conversations[conv_id].append(tweet)
            else:
                ungrouped_tweets.append(tweet)
        
        # Write all tweets to output file (grouped by conversation_id)
        output_file = Path(__file__).parent / "output_get_users_tweets.json"
        output_data = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'total_tweets': len(all_tweets),
            'total_conversations': len(conversations),
            'conversations': {
                conv_id: {
                    'conversation_id': conv_id,
                    'tweet_count': len(tweets),
                    'tweets': tweets
                }
                for conv_id, tweets in conversations.items()
            },
            'ungrouped_tweets': ungrouped_tweets
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
        
        # Compute start_time based on "post-age-within" hours
        hours_within_env = os.environ.get("HOME_TIMELINE_POST_AGE_WITHIN_HOURS")
        try:
            hours_within = int(hours_within_env) if hours_within_env is not None else 48
        except ValueError:
            logger.warning(f"Invalid HOME_TIMELINE_POST_AGE_WITHIN_HOURS='{hours_within_env}', defaulting to 48 hours")
            hours_within = 48
        
        now_utc = datetime.now(timezone.utc)
        start_dt = now_utc - timedelta(hours=hours_within)
        start_time_str = format_rfc3339(start_dt)
        logger.info(f"Using start_time (now - {hours_within}h): {start_time_str}")
        
        # Build query parameters
        params = {
            'tweet.fields': ','.join(['note_tweet', 'created_at', 'author_id', 'public_metrics', 'text', 'entities', 'conversation_id']),
            'expansions': 'referenced_tweets.id,author_id',
            'user.fields': 'username,name',
            'start_time': start_time_str,
            'max_results': 30
        }
        
        # Make API request with OAuth 1.0a
        # Note: The home timeline endpoint requires the authenticated user's ID
        # We'll use /users/me first to get the user ID, then use that ID
        
        # First, get the authenticated user's ID using /2/users/me
        me_headers = {
            'Authorization': generate_oauth1_header(
                f"{BASE_URL}/users/me",
                'GET',
                credentials
            )
        }
        
        me_response = make_api_request(f"{BASE_URL}/users/me", me_headers)
        user_id = me_response['data']['id']
        logger.info(f"Authenticated user ID: {user_id}")
        
        # Now fetch home timeline
        timeline_url = f"{BASE_URL}/users/{user_id}/timelines/reverse_chronological"
        headers = {
            'Authorization': generate_oauth1_header(timeline_url, 'GET', credentials, params)
        }
        
        response_data = make_api_request(timeline_url, headers, params)
        
        # Build user map from includes.users
        user_map: Dict[str, Optional[str]] = {}
        includes = response_data.get('includes', {})
        if 'users' in includes:
            for user in includes['users']:
                user_id = user.get('id')
                username = user.get('username')
                if user_id:
                    user_map[str(user_id)] = username
        
        # Process tweets
        tweets_data = []
        if 'data' in response_data:
            for tweet in response_data['data']:
                tweet_dict = build_tweet_dict(tweet, user_map)
                tweets_data.append(tweet_dict)
            
            logger.info(f"Found {len(response_data['data'])} tweets in home timeline")
        else:
            logger.info("No tweets found in home timeline")
        
        # Group tweets by conversation_id
        conversations: Dict[str, List[Dict[str, Any]]] = {}
        ungrouped_tweets: List[Dict[str, Any]] = []
        
        for tweet in tweets_data:
            conv_id = tweet.get('conversation_id')
            if conv_id:
                if conv_id not in conversations:
                    conversations[conv_id] = []
                conversations[conv_id].append(tweet)
            else:
                ungrouped_tweets.append(tweet)
        
        # Write tweets to output file (grouped by conversation_id)
        output_file = Path(__file__).parent / "output_get_home_timeline.json"
        output_data = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'total_tweets': len(tweets_data),
            'total_conversations': len(conversations),
            'conversations': {
                conv_id: {
                    'conversation_id': conv_id,
                    'tweet_count': len(tweets),
                    'tweets': tweets
                }
                for conv_id, tweets in conversations.items()
            },
            'ungrouped_tweets': ungrouped_tweets
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
