#!/usr/bin/env python3
"""
Weekly Market Outlook Bot for GitHub Actions
Runs every Sunday for the week ahead analysis
Original version with 400 error fix
"""

import os
import requests
import json
import asyncio
import aiohttp
from datetime import datetime, timedelta
import pytz
from openai import OpenAI
import feedparser
from typing import List, Dict
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class WeeklyOutlookBot:
    def __init__(self):
        print("🗓️ INITIALIZING WEEKLY MARKET OUTLOOK BOT")
        print("=" * 50)
        
        # Load environment variables
        try:
            from dotenv import load_dotenv
            if os.path.exists('.env'):
                load_dotenv()
                print("📁 Using local .env file")
            else:
                print("🔧 Using GitHub Actions environment variables")
        except ImportError:
            print("🔧 Using system environment variables")
        
        # Get environment variables
        openai_key = os.getenv('OPENAI_API_KEY')
        webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
        news_key = os.getenv('NEWS_API_KEY')
        
        # Validate required environment variables
        if not openai_key:
            raise ValueError("❌ OPENAI_API_KEY environment variable is required")
        if not webhook_url:
            raise ValueError("❌ DISCORD_WEBHOOK_URL environment variable is required")
            
        self.openai_client = OpenAI(api_key=openai_key)
        self.webhook_url = webhook_url
        self.news_api_key = news_key
        
        # Financial news sources
        self.news_sources = [
            'reuters', 'bloomberg', 'cnbc', 'marketwatch',
            'yahoo-finance', 'the-wall-street-journal'
        ]
        
        # Major market symbols and sectors to monitor
        self.watchlist = [
            'SPY', 'QQQ', 'IWM', 'DIA',  # Major ETFs
            'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA', 'META',  # Tech leaders
            'XLF', 'XLE', 'XLK', 'XLV', 'XLI'  # Sector ETFs
        ]
        
        self.est = pytz.timezone('US/Eastern')
        print("✅ Weekly outlook bot initialized successfully!")
        print("=" * 50)
    
    def test_openai(self):
        """Test OpenAI API connectivity"""
        print("🧪 Testing OpenAI API connection...")
        
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "user", "content": "Say 'Weekly outlook API test successful' in exactly those words."}
                ],
                max_tokens=10
            )
            
            result = response.choices[0].message.content.strip()
            print("✅ OpenAI API connection successful!")
            return True
            
        except Exception as e:
            print(f"❌ OpenAI API test failed: {e}")
            return False

    async def fetch_weekend_news(self, days_back: int = 3) -> List[Dict]:
        """Fetch weekend and recent financial news"""
        print(f"📰 Fetching weekend news from last {days_back} days...")
        
        articles = []
        from_time = datetime.now() - timedelta(days=days_back)
        
        try:
            # Try News API first if available
            if self.news_api_key:
                print("📡 Fetching from News API...")
                articles.extend(await self._fetch_from_newsapi(from_time))
            else:
                print("📡 News API key not provided, using RSS feeds only")
            
            # Always fetch from RSS feeds
            print("📡 Fetching from RSS feeds...")
            rss_articles = await self._fetch_from_rss()
            articles.extend(rss_articles)
            
            # Remove duplicates and sort by relevance
            unique_articles = self._deduplicate_articles(articles)
            sorted_articles = sorted(unique_articles, key=lambda x: x.get('relevance_score', 0), reverse=True)[:15]
            
            print(f"📊 Found {len(sorted_articles)} relevant articles for weekly analysis")
            return sorted_articles
            
        except Exception as e:
            print(f"❌ Error fetching weekend news: {e}")
            logger.error(f"Error fetching weekend news: {e}")
            return []
    
    async def _fetch_from_newsapi(self, from_time: datetime) -> List[Dict]:
        """Fetch from News API"""
        articles = []
        
        url = "https://newsapi.org/v2/everything"
        params = {
            'apiKey': self.news_api_key,
            'sources': ','.join(self.news_sources),
            'from': from_time.isoformat(),
            'sortBy': 'relevancy',
            'language': 'en',
            'pageSize': 60
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params=params) as response:
                    if response.status == 200:
                        data = await response.json()
                        news_articles = data.get('articles', [])
                        
                        for article in news_articles:
                            if article.get('title') and article.get('description'):
                                articles.append({
                                    'title': article['title'],
                                    'description': article['description'],
                                    'url': article['url'],
                                    'source': article['source']['name'],
                                    'published_at': article['publishedAt'],
                                    'relevance_score': self._calculate_relevance(article)
                                })
                    else:
                        print(f"⚠️ News API returned status {response.status}")
                        
            except Exception as e:
                print(f"❌ Error fetching from News API: {e}")
        
        return articles
    
    async def _fetch_from_rss(self) -> List[Dict]:
        """Fetch from RSS feeds"""
        articles = []
        rss_feeds = [
            'https://feeds.bloomberg.com/markets/news.rss',
            'https://www.cnbc.com/id/100003114/device/rss/rss.html',
            'https://www.marketwatch.com/rss/topstories',
            'https://feeds.reuters.com/reuters/businessNews'
        ]
        
        for feed_url in rss_feeds:
            try:
                feed = feedparser.parse(feed_url)
                
                for entry in feed.entries[:10]:  # More articles for weekly analysis
                    if hasattr(entry, 'title') and hasattr(entry, 'link'):
                        articles.append({
                            'title': entry.title,
                            'description': getattr(entry, 'summary', entry.title)[:200],
                            'url': entry.link,
                            'source': feed.feed.get('title', 'RSS Feed'),
                            'published_at': getattr(entry, 'published', ''),
                            'relevance_score': self._calculate_relevance({
                                'title': entry.title, 
                                'description': getattr(entry, 'summary', '')
                            })
                        })
                        
            except Exception as e:
                print(f"❌ Error fetching RSS feed: {e}")
                
        return articles
    
    def _calculate_relevance(self, article: Dict) -> int:
        """Calculate relevance score for weekly outlook"""
        score = 0
        text = f"{article.get('title', '')} {article.get('description', '')}".lower()
        
        # High-priority weekly outlook keywords
        high_keywords = [
            'federal reserve', 'fed', 'interest rate', 'inflation', 'gdp', 'unemployment',
            'earnings', 'guidance', 'outlook', 'forecast', 'economic data', 'jobs report',
            'fomc', 'ppi', 'cpi', 'retail sales', 'manufacturing', 'consumer confidence'
        ]
        
        # Medium-priority keywords
        medium_keywords = [
            'merger', 'acquisition', 'ipo', 'analyst', 'upgrade', 'downgrade',
            'dividend', 'split', 'buyback', 'guidance', 'revenue', 'profit'
        ]
        
        # Weekly/trend keywords
        weekly_keywords = [
            'week ahead', 'outlook', 'forecast', 'preview', 'expectations',
            'trend', 'momentum', 'technical analysis', 'support', 'resistance'
        ]
        
        for keyword in high_keywords:
            if keyword in text:
                score += 4
                
        for keyword in medium_keywords:
            if keyword in text:
                score += 2
                
        for keyword in weekly_keywords:
            if keyword in text:
                score += 3
                
        # Watchlist symbols
        for symbol in self.watchlist:
            if symbol.lower() in text or f"${symbol.lower()}" in text:
                score += 3
                
        return score
    
    def _deduplicate_articles(self, articles: List[Dict]) -> List[Dict]:
        """Remove duplicate articles"""
        unique_articles = []
        seen_titles = set()
        
        for article in articles:
            title_words = set(article['title'].lower().split())
            is_duplicate = False
            
            for seen_title in seen_titles:
                seen_words = set(seen_title.split())
                overlap = len(title_words & seen_words) / max(len(title_words), len(seen_words))
                if overlap > 0.7:
                    is_duplicate = True
                    break
                    
            if not is_duplicate:
                unique_articles.append(article)
                seen_titles.add(article['title'].lower())
                
        return unique_articles
    
    async def generate_weekly_outlook(self, articles: List[Dict]) -> str:
        """Generate AI-powered weekly market outlook"""
        print("🤖 Generating weekly market outlook...")
        
        if not articles:
            return "Limited news available for this week's outlook. Focus on major economic indicators and earnings releases."
            
        # Prepare articles for GPT
        news_text = "\n\n".join([
            f"**{article['title']}** ({article['source']})\n{article['description'][:200]}"
            for article in articles[:12]
        ])
        
        current_time = datetime.now(self.est)
        next_monday = current_time + timedelta(days=(7 - current_time.weekday()) % 7)
        week_range = f"{next_monday.strftime('%B %d')} - {(next_monday + timedelta(days=4)).strftime('%B %d, %Y')}"
        
        prompt = f"""
        As a senior financial analyst, provide a comprehensive weekly market outlook for the trading week of {week_range}.
        
        Based on recent financial news and market developments, analyze:
        
        1. **Week Ahead Theme**: What's the overarching narrative for this trading week?
        2. **Key Economic Events**: Important data releases, Fed speeches, earnings reports to watch
        3. **Sector Focus**: Which sectors/industries are likely to be in focus and why?
        4. **Technical Levels**: Major support/resistance levels for key indices ($SPY, $QQQ, $IWM)
        5. **Risk Factors**: What could derail markets or create volatility?
        6. **Trading Opportunities**: Potential setups, themes, or catalysts to monitor
        7. **Week's Wildcards**: Unexpected events or under-the-radar catalysts
        
        Keep it professional and actionable (400-500 words). Use bullet points for key highlights.
        Include relevant symbols where appropriate (e.g., $SPY, $AAPL, $XLF).
        Focus on what traders and investors should prioritize this week.
        
        Recent News & Market Developments:
        {news_text}
        """
        
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a senior financial analyst providing weekly market outlooks for professional traders and investors. Focus on actionable insights and key catalysts."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=600,
                temperature=0.2
            )
            
            outlook = response.choices[0].message.content.strip()
            print("✅ Weekly outlook generated successfully!")
            return outlook
            
        except Exception as e:
            print(f"❌ Error generating weekly outlook: {e}")
            logger.error(f"Error generating weekly outlook: {e}")
            return "Unable to generate weekly outlook at this time. Focus on major economic indicators, earnings releases, and Fed communications for the week ahead."
    
    def send_weekly_discord_webhook(self, outlook: str, articles: List[Dict]):
        """Send weekly outlook via Discord webhook"""
        print("📤 Sending weekly market outlook to Discord...")
        
        current_time = datetime.now(self.est)
        next_monday = current_time + timedelta(days=(7 - current_time.weekday()) % 7)
        week_range = f"{next_monday.strftime('%B %d')} - {(next_monday + timedelta(days=4)).strftime('%B %d, %Y')}"
        
        # Smart splitting for long outlook
        def split_outlook(text: str, max_length: int = 1000) -> List[str]:
            if len(text) <= max_length:
                return [text]
            
            parts = []
            paragraphs = text.split('\n\n')
            current_part = ""
            
            for paragraph in paragraphs:
                if len(current_part + paragraph + '\n\n') > max_length:
                    if current_part.strip():
                        parts.append(current_part.strip())
                        current_part = ""
                    
                    if len(paragraph) > max_length:
                        sentences = paragraph.split('. ')
                        temp_part = ""
                        
                        for sentence in sentences:
                            if len(temp_part + sentence + '. ') <= max_length:
                                temp_part += sentence + '. '
                            else:
                                if temp_part.strip():
                                    parts.append(temp_part.strip())
                                temp_part = sentence + '. '
                        
                        if temp_part.strip():
                            current_part = temp_part
                    else:
                        current_part = paragraph + '\n\n'
                else:
                    current_part += paragraph + '\n\n'
            
            if current_part.strip():
                parts.append(current_part.strip())
            
            return parts
        
        # Split outlook into manageable parts
        outlook_parts = split_outlook(outlook)
        
        # Create fields for outlook
        outlook_fields = []
        for i, part in enumerate(outlook_parts):
            field_name = "📊 Weekly Market Outlook" if i == 0 else "\u200b"
            outlook_fields.append({
                "name": field_name,
                "value": part,
                "inline": False
            })
        
        # Main embed
        main_embed = {
            "title": "📅 Weekly Trading Outlook",
            "description": f"**Week of {week_range}**\n*{current_time.strftime('%A, %B %d, %Y - %I:%M %p EST')}*",
            "color": 0x9932cc,  # Purple for weekly outlook
            "fields": outlook_fields,
            "footer": {
                "text": "Weekly market analysis • Plan your trading week • Not financial advice"
            },
            "timestamp": current_time.isoformat()
        }
        
        # Key stories embed
        if articles:
            stories_text = "\n".join([
                f"• [{article['title'][:70]}...]({article['url']})"
                for article in articles[:8]
            ])
            
            stories_embed = {
                "title": "📰 Key Stories Shaping the Week",
                "description": stories_text,
                "color": 0x0066cc,  # Blue
            }
        else:
            stories_embed = {
                "title": "📰 Key Stories",
                "description": "Monitor major financial news sources for developing stories.",
                "color": 0x999999,  # Gray
            }
        
        # Week ahead calendar
        calendar_embed = {
            "title": "📋 Week Ahead Checklist",
            "description": "**Monday:** Review weekend news, set weekly levels\n**Tuesday-Thursday:** Monitor earnings, economic data\n**Friday:** Weekly close, next week preparation\n\n**Market Hours:** 9:30 AM - 4:00 PM EST",
            "color": 0xff6600,  # Orange
        }
        
        # Prepare webhook payload
        payload = {
            "content": "📈 **Weekly Market Outlook is here!** Plan your trading week:",
            "embeds": [main_embed, stories_embed, calendar_embed],
            "username": "Weekly Market Outlook",
            "avatar_url": "https://cdn-icons-png.flaticon.com/512/2784/2784403.png"
        }
        
        try:
            # Clean the payload to prevent 400 errors
            payload_str = json.dumps(payload, ensure_ascii=False)
            # Remove any problematic null characters
            payload_str = payload_str.replace('\u0000', '').replace('\x00', '')
            cleaned_payload = json.loads(payload_str)
            
            response = requests.post(self.webhook_url, json=cleaned_payload, timeout=30)
            response.raise_for_status()
            print("✅ Weekly outlook sent successfully to Discord!")
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                print("⚠️ Discord rejected payload, trying simplified version...")
                # Fallback to simple format only if 400 error
                simple_payload = {
                    "content": f"📅 **Weekly Market Outlook - {week_range}**\n\n{outlook[:1800]}",
                    "username": "Weekly Market Outlook"
                }
                response = requests.post(self.webhook_url, json=simple_payload, timeout=30)
                response.raise_for_status()
                print("✅ Sent simplified weekly outlook!")
            else:
                print(f"❌ Failed to send Discord webhook: {e}")
                logger.error(f"Failed to send Discord webhook: {e}")
                raise
        except requests.exceptions.RequestException as e:
            print(f"❌ Failed to send Discord webhook: {e}")
            logger.error(f"Failed to send Discord webhook: {e}")
            raise

async def main():
    """Main function for weekly outlook bot"""
    print("📅 WEEKLY MARKET OUTLOOK BOT")
    print("=" * 40)
    current_time = datetime.now(pytz.timezone('US/Eastern'))
    print(f"⏰ Starting at: {current_time.strftime('%A, %B %d, %Y - %I:%M %p EST')}")
    print("=" * 40)
    
    try:
        # Initialize bot
        bot = WeeklyOutlookBot()
        
        # Test OpenAI connectivity
        if not bot.test_openai():
            print("❌ OpenAI connection failed - aborting")
            return
            
        print("\n📅 GENERATING WEEKLY OUTLOOK")
        print("=" * 40)
        
        # Fetch weekend news
        logger.info("Fetching weekend and recent news...")
        articles = await bot.fetch_weekend_news(days_back=3)
        
        # Generate weekly outlook
        logger.info("Generating weekly market outlook...")
        outlook = await bot.generate_weekly_outlook(articles)
        
        # Send to Discord
        logger.info("Sending weekly outlook to Discord...")
        bot.send_weekly_discord_webhook(outlook, articles)
        
        print("\n🎉 SUCCESS!")
        print("=" * 20)
        logger.info("Weekly market outlook completed successfully!")
        
    except Exception as e:
        print(f"\n💥 ERROR: {str(e)}")
        logger.error(f"Error in weekly outlook: {e}")
        
        # Try to send error notification
        try:
            webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
            if webhook_url:
                error_payload = {
                    "content": f"❌ **Error in weekly outlook bot:** {str(e)[:200]}",
                    "username": "Weekly Outlook Bot - ERROR"
                }
                requests.post(webhook_url, json=error_payload)
        except:
            pass
        raise

if __name__ == "__main__":
    asyncio.run(main())