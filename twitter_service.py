# twitter_service.py
import tweepy
import os

# Tweepy 클라이언트 초기화 (환경변수 사용)
client = tweepy.Client(
    consumer_key=os.environ.get("TWITTER_CONSUMER_KEY"),
    consumer_secret=os.environ.get("TWITTER_CONSUMER_SECRET"),
    access_token=os.environ.get("TWITTER_ACCESS_TOKEN"),
    access_token_secret=os.environ.get("TWITTER_ACCESS_SECRET")
)

def post_to_twitter(content):
    """트위터에 글을 게시하는 공통 함수"""
    try:
        response = client.create_tweet(text=content)
        return True, response.data['id']
    except Exception as e:
        print(f"❌ 트위터 전송 실패: {e}")
        return False, str(e)
