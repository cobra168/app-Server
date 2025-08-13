from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import re
import time
import os
import sys
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

class TorrentScraper:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

    def preprocess_search_query(self, query):
        """
        Preprocess search query to handle common misspellings and improve results
        """
        # Common misspellings and corrections
        corrections = {
            'narto': 'naruto',
            'naroto': 'naruto', 
            'naurto': 'naruto',
            'lord of ring': 'lord of rings',
            'lord rings': 'lord of rings',
            'jumanji jungle': 'jumanji welcome to the jungle',
            'last us': 'last of us',
            'sand man': 'sandman',
            'avengers end game': 'avengers endgame',
            'spiderman': 'spider-man',
            'batman vs superman': 'batman v superman',
            'starwars': 'star wars',
            'harrypotter': 'harry potter',
            'gameofthrones': 'game of thrones',
            'breakingbad': 'breaking bad',
            'walkingdead': 'walking dead'
        }
        
        processed = query.lower().strip()
        
        # Apply corrections
        for wrong, correct in corrections.items():
            if wrong in processed:
                processed = processed.replace(wrong, correct)
                
        return processed

    def scrape_site(self, query, category=None):
        """
        Scrape torrent data from The Pirate Bay
        """
        results = []

        try:
            # The Pirate Bay search URLs
            search_urls = [
                f"https://thepiratebay.org/search/{query}/1/99/0",
                f"https://piratebay.party/search/{query}/1/99/0",
                f"https://tpb.party/search/{query}/1/99/0",
            ]

            for url in search_urls:
                try:
                    response = requests.get(url, headers=self.headers, timeout=15)
                    if response.status_code == 200:
                        soup = BeautifulSoup(response.content, 'html.parser')
                        site_results = self.parse_piratebay_results(soup, url)
                        results.extend(site_results)
                        if site_results:  # If we got results, no need to try other mirrors
                            break

                    # Be respectful - add delay between requests
                    time.sleep(2)

                except Exception as e:
                    logger.error(f"Error scraping {url}: {e}")
                    continue

        except Exception as e:
            logger.error(f"General scraping error: {e}")

        return results

    def parse_piratebay_results(self, soup, source_url):
        """
        Parse Pirate Bay HTML and extract torrent information
        """
        results = []

        # Find the main search results table - look for table with id searchResult or class searchResult
        search_table = soup.find('table', {'id': 'searchResult'}) or soup.find('table', {'class': 'searchResult'})
        
        if not search_table:
            # Try alternative selectors
            search_table = soup.find('table')
        
        if not search_table:
            logger.warning("No search results table found")
            return results

        # Find all torrent rows, skip the header
        torrent_rows = search_table.find_all('tr')[1:]  # Skip header row

        for i, row in enumerate(torrent_rows):
            try:
                # Get all td elements in the row
                tds = row.find_all('td')
                if len(tds) < 4:  # Need at least name, seeders, leechers, size
                    continue

                # First td usually contains category info, second contains name and details
                name_td = tds[1] if len(tds) > 1 else tds[0]
                
                # Find the title link - it's usually the first or second link in the name td
                title_elem = name_td.find('a', {'class': 'detLink'})
                if not title_elem:
                    # Try alternative selectors
                    title_elem = name_td.find('a')
                    if not title_elem:
                        continue

                title = title_elem.get_text().strip()
                details_url = title_elem.get('href', '')
                if details_url and not details_url.startswith('http'):
                    details_url = source_url.split('/search')[0] + details_url

                # Find magnet link - look for magnet: href
                magnet_link = ''
                magnet_links = row.find_all('a', href=re.compile(r'^magnet:'))
                if magnet_links:
                    magnet_link = magnet_links[0].get('href')

                # Parse description for size and upload info
                desc_elem = name_td.find('font', {'class': 'detDesc'})
                size = 'Unknown'
                uploaded = 'Unknown'
                
                if desc_elem:
                    desc_text = desc_elem.get_text()
                    
                    # Extract size - try multiple patterns
                    size_patterns = [
                        r'Size[\s:]+([0-9.]+\s*[KMGT]?i?B)',
                        r'([0-9.]+\s*[KMGT]?i?B)',
                        r'Size\s*([0-9.]+\s*[KMGT]B)',
                        r',\s*Size\s+([^,]+)',
                    ]
                    
                    for pattern in size_patterns:
                        size_match = re.search(pattern, desc_text, re.IGNORECASE)
                        if size_match:
                            size = size_match.group(1).strip()
                            break
                    
                    # Extract upload date - try multiple patterns
                    upload_patterns = [
                        r'Uploaded[\s:]+([^,]+)',
                        r'Uploaded\s+([^,]+),',
                        r'(\d{2}-\d{2}\s+\d{4})',
                        r'(\d{4}-\d{2}-\d{2})',
                        r'(Today|Yesterday|\d+\s+mins?\s+ago|\d+\s+hours?\s+ago)',
                    ]
                    
                    for pattern in upload_patterns:
                        upload_match = re.search(pattern, desc_text, re.IGNORECASE)
                        if upload_match:
                            uploaded = upload_match.group(1).strip()
                            break
                
                # Try alternative extraction from other elements if not found in detDesc
                if size == 'Unknown' or uploaded == 'Unknown':
                    # Look for size and date in other font elements or text nodes
                    all_fonts = name_td.find_all('font')
                    for font in all_fonts:
                        font_text = font.get_text()
                        
                        # Try to extract size from any font element
                        if size == 'Unknown':
                            size_match = re.search(r'([0-9.]+\s*[KMGT]?i?B)', font_text, re.IGNORECASE)
                            if size_match:
                                size = size_match.group(1)
                        
                        # Try to extract date from any font element
                        if uploaded == 'Unknown':
                            date_match = re.search(r'(\d{2}-\d{2}\s+\d{4}|\d{4}-\d{2}-\d{2}|Today|Yesterday)', font_text, re.IGNORECASE)
                            if date_match:
                                uploaded = date_match.group(1)

                # Get seeders and leechers from the last two columns
                seeders = '0'
                leechers = '0'
                
                if len(tds) >= 3:
                    try:
                        # Seeders are usually in the second to last column
                        seeders_td = tds[-2]
                        seeders = re.sub(r'[^\d]', '', seeders_td.get_text().strip()) or '0'
                        
                        # Leechers are usually in the last column
                        leechers_td = tds[-1]
                        leechers = re.sub(r'[^\d]', '', leechers_td.get_text().strip()) or '0'
                    except:
                        pass

                result = {
                    'id': i + 1,
                    'title': title,
                    'magnet_link': magnet_link,
                    'details_url': details_url,
                    'size': size,
                    'seeders': seeders,
                    'leechers': leechers,
                    'uploaded': uploaded,
                    'source': source_url,
                    'description': f"Torrent: {title}",
                    'files': [],
                    'category': self.guess_category(title)
                }
                results.append(result)
                logger.info(f"Found torrent: {title} | Size: {size} | Uploaded: {uploaded} | Seeders: {seeders}")

            except Exception as e:
                logger.error(f"Error parsing row {i}: {e}")
                continue

        logger.info(f"Total results found: {len(results)}")
        return results

    def guess_category(self, title):
        """
        Guess category based on title with improved keyword detection
        """
        title_lower = title.lower()
        
        # Video keywords (expanded)
        video_keywords = [
            'movie', 'film', '1080p', '720p', '4k', 'bluray', 'dvd', 'mkv', 'mp4', 
            'avi', 'mov', 'wmv', 'flv', 'webm', 'm4v', 'series', 'episode', 'season',
            'tv', 'show', 'documentary', 'anime', 'cartoon', 'netflix', 'hulu', 
            'amazon', 'disney', 'hbo', 'streaming', 'webrip', 'brrip', 'hdtv'
        ]
        
        # Audio keywords (expanded)
        audio_keywords = [
            'album', 'music', 'mp3', 'flac', 'song', 'band', 'artist', 'soundtrack', 
            'audio', 'wav', 'aac', 'ogg', 'vinyl', 'cd', 'single', 'ep', 'lp',
            'remix', 'live', 'concert', 'acoustic', 'instrumental'
        ]
        
        # Games keywords (expanded)
        games_keywords = [
            'game', 'pc', 'xbox', 'ps4', 'ps5', 'nintendo', 'crack', 'steam', 
            'gaming', 'console', 'playstation', 'switch', 'repack', 'gog', 
            'origin', 'uplay', 'epic', 'rpg', 'fps', 'mmo', 'indie'
        ]
        
        # Applications keywords (expanded)
        apps_keywords = [
            'software', 'app', 'program', 'tool', 'windows', 'mac', 'linux',
            'application', 'utility', 'portable', 'installer', 'setup', 'patch',
            'update', 'driver', 'plugin', 'extension', 'addon', 'framework'
        ]
        
        if any(word in title_lower for word in video_keywords):
            return 'Video'
        elif any(word in title_lower for word in audio_keywords):
            return 'Audio'
        elif any(word in title_lower for word in games_keywords):
            return 'Games'
        elif any(word in title_lower for word in apps_keywords):
            return 'Applications'
        else:
            return 'Other'

    def get_torrent_details(self, torrent_url):
        """
        Get detailed information about a specific torrent from Pirate Bay
        """
        try:
            response = requests.get(torrent_url, headers=self.headers, timeout=15)
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')

                # Extract detailed information from Pirate Bay format
                description_elem = soup.find('div', class_='nfo')
                if not description_elem:
                    description_elem = soup.find('div', id='desc')

                description = description_elem.get_text().strip() if description_elem else 'No description available'

                # Find magnet link
                magnet_elem = soup.find('a', href=re.compile(r'^magnet:'))
                magnet_link = magnet_elem.get('href') if magnet_elem else ''

                # Try to find file list
                files = []
                file_table = soup.find('table', {'class': 'filelist'})
                if file_table:
                    file_rows = file_table.find_all('tr')[1:]  # Skip header
                    for row in file_rows:
                        tds = row.find_all('td')
                        if len(tds) >= 2:
                            filename = tds[0].get_text().strip()
                            filesize = tds[1].get_text().strip()
                            files.append({'name': filename, 'size': filesize})

                return {
                    'description': description,
                    'magnet_link': magnet_link,
                    'files': files
                }

        except Exception as e:
            logger.error(f"Error getting torrent details: {e}")
            return None

# Initialize scraper
scraper = TorrentScraper()

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/api/search', methods=['POST'])
def search_torrents():
    try:
        data = request.get_json()
        query = data.get('query', '').strip()
        categories = data.get('categories', [])
        
        if not query:
            return jsonify({'success': False, 'error': 'Query is required'})
        
        # Preprocess the query
        processed_query = scraper.preprocess_search_query(query)
        logger.info(f"Searching for: {processed_query}")
        
        # Scrape torrents
        results = scraper.scrape_site(processed_query)
        
        # Filter by categories if specified
        if categories and 'all' not in categories:
            results = [r for r in results if r['category'].lower() in [c.lower() for c in categories]]
        
        return jsonify({
            'success': True,
            'results': results,
            'total': len(results),
            'query': processed_query
        })
        
    except Exception as e:
        logger.error(f"Search error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/details', methods=['POST'])
def get_torrent_details():
    try:
        data = request.get_json()
        torrent_url = data.get('url', '').strip()
        
        if not torrent_url:
            return jsonify({'success': False, 'error': 'URL is required'})
        
        details = scraper.get_torrent_details(torrent_url)
        
        if details:
            return jsonify({
                'success': True,
                'details': details
            })
        else:
            return jsonify({'success': False, 'error': 'Could not fetch details'})
            
    except Exception as e:
        logger.error(f"Details error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/proxy', methods=['POST'])
def proxy_request():
    """Proxy requests to avoid CORS issues"""
    try:
        data = request.get_json()
        url = data.get('url', '').strip()
        
        if not url:
            return jsonify({'success': False, 'error': 'URL is required'})
        
        response = requests.get(url, headers=scraper.headers, timeout=15)
        
        return jsonify({
            'success': True,
            'content': response.text,
            'status_code': response.status_code
        })
        
    except Exception as e:
        logger.error(f"Proxy error: {e}")
        return jsonify({'success': False, 'error': str(e)})

# HLS Streaming with FFmpeg
@app.route('/api/create-hls-stream', methods=['POST'])
def create_hls_stream():
    try:
        data = request.get_json()
        magnet = data.get('magnet', '').strip()
        file_name = data.get('fileName', '')
        file_index = data.get('fileIndex', 0)
        title = data.get('title', 'Unknown')
        
        if not magnet or not magnet.startswith('magnet:'):
            return jsonify({'success': False, 'error': 'Valid magnet link required'})
        
        # Create unique stream ID
        import hashlib
        import time
        stream_id = hashlib.md5(f"{magnet}{file_name}{time.time()}".encode()).hexdigest()[:16]
        
        # Start HLS transcoding process
        result = start_hls_transcoding(magnet, file_name, file_index, stream_id, title)
        
        if result['success']:
            return jsonify({
                'success': True,
                'streamId': stream_id,
                'playlistUrl': f'/api/hls-stream/{stream_id}/playlist.m3u8'
            })
        else:
            return jsonify({'success': False, 'error': result['error']})
            
    except Exception as e:
        logger.error(f"HLS stream creation error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/hls-stream/<stream_id>/playlist.m3u8')
def serve_hls_playlist(stream_id):
    try:
        playlist_path = f'/tmp/hls-{stream_id}/playlist.m3u8'
        if os.path.exists(playlist_path):
            with open(playlist_path, 'r') as f:
                playlist_content = f.read()
            
            response = app.response_class(
                playlist_content,
                mimetype='application/vnd.apple.mpegurl'
            )
            response.headers['Access-Control-Allow-Origin'] = '*'
            return response
        else:
            return jsonify({'error': 'Playlist not found'}), 404
            
    except Exception as e:
        logger.error(f"Error serving HLS playlist: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/hls-stream/<stream_id>/<segment>')
def serve_hls_segment(stream_id, segment):
    try:
        segment_path = f'/tmp/hls-{stream_id}/{segment}'
        if os.path.exists(segment_path):
            return send_from_directory(f'/tmp/hls-{stream_id}', segment, mimetype='video/mp2t')
        else:
            return jsonify({'error': 'Segment not found'}), 404
            
    except Exception as e:
        logger.error(f"Error serving HLS segment: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/cleanup-hls-stream', methods=['POST'])
def cleanup_hls_stream():
    try:
        data = request.get_json()
        stream_id = data.get('streamId', '')
        
        if stream_id:
            cleanup_hls_files(stream_id)
            
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"HLS cleanup error: {e}")
        return jsonify({'success': False, 'error': str(e)})

def start_hls_transcoding(magnet, file_name, file_index, stream_id, title):
    """Start FFmpeg HLS transcoding process"""
    try:
        import subprocess
        import threading
        
        # Create output directory
        output_path = f'/tmp/hls-{stream_id}'
        os.makedirs(output_path, exist_ok=True)
        
        # Start transcoding in background thread
        def transcode():
            try:
                # Use WebTorrent CLI or aria2c to download and pipe to FFmpeg
                # For now, we'll create a mock implementation
                create_mock_hls_playlist(output_path, stream_id)
                
            except Exception as e:
                logger.error(f"Transcoding error: {e}")
        
        threading.Thread(target=transcode, daemon=True).start()
        
        return {'success': True, 'streamId': stream_id}
        
    except Exception as e:
        logger.error(f"Failed to start HLS transcoding: {e}")
        return {'success': False, 'error': str(e)}

def create_mock_hls_playlist(output_path, stream_id):
    """Create a mock HLS playlist for demonstration"""
    try:
        # Create playlist file
        playlist_content = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:10
#EXT-X-MEDIA-SEQUENCE:0
#EXT-X-PLAYLIST-TYPE:VOD
#EXTINF:10.0,
segment000.ts
#EXTINF:10.0,
segment001.ts
#EXTINF:10.0,
segment002.ts
#EXTINF:10.0,
segment003.ts
#EXTINF:10.0,
segment004.ts
#EXT-X-ENDLIST
"""
        
        playlist_path = os.path.join(output_path, 'playlist.m3u8')
        with open(playlist_path, 'w') as f:
            f.write(playlist_content)
        
        # Create mock segment files (empty for now)
        for i in range(5):
            segment_path = os.path.join(output_path, f'segment{i:03d}.ts')
            with open(segment_path, 'wb') as f:
                f.write(b'') # Empty file for now
                
    except Exception as e:
        logger.error(f"Error creating mock HLS playlist: {e}")

def cleanup_hls_files(stream_id):
    """Clean up HLS files for a stream"""
    try:
        import shutil
        output_path = f'/tmp/hls-{stream_id}'
        if os.path.exists(output_path):
            shutil.rmtree(output_path)
            logger.info(f"Cleaned up HLS files for stream {stream_id}")
    except Exception as e:
        logger.error(f"Error cleaning up HLS files: {e}")

# Health check endpoint
@app.route('/health')
def health_check():
    return jsonify({'status': 'healthy', 'message': 'Backend is running'})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8000))  # Render gives us a port
    logger.info(f"Starting StreamVault backend on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False)
