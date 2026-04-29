import tweepy
import os

def get_client():
    # 여기서 None인지 체크합니다.
    ckey = os.environ.get("TWITTER_CONSUMER_KEY")
    csec = os.environ.get("TWITTER_CONSUMER_SECRET")
    atkn = os.environ.get("TWITTER_ACCESS_TOKEN")
    atsec = os.environ.get("TWITTER_ACCESS_SECRET")
    
    if not all([ckey, csec, atkn, atsec]):
        print("❌ ERROR: 트위터 환경 변수 중 일부가 설정되지 않았습니다!")
        return None
        
    return tweepy.Client(
        consumer_key=ckey,
        consumer_secret=csec,
        access_token=atkn,
        access_token_secret=atsec
    )

def post_to_twitter(content):
    client = get_client()
    if client is None:
        return False, "Auth Keys Missing"
        
    try:
        response = client.create_tweet(text=content)
        return True, response.data['id']
    except Exception as e:
        print(f"❌ 트위터 전송 실패: {e}")
        return False, str(e)
