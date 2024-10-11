import requests
import streamlit as st
import pandas as pd
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configures the page in ‘wide’ mode with a title and an icon
st.set_page_config(
    page_title='Fetching WordPress Posts via REST API',
    page_icon='📝',
    layout='wide'
)


def validate_wordpress_site(url):
    """Validate that the URL is a WordPress site with an accessible REST API."""
    # Parse the URL to ensure it has a valid format
    parsed_url = urlparse(url)
    if not parsed_url.scheme or not parsed_url.netloc:
        return False, "Invalid URL format. Please include the scheme (http:// or https://)."

    # Construct the REST API endpoint URL
    api_url = f"{parsed_url.scheme}://{parsed_url.netloc}/wp-json/"

    try:
        response = requests.get(api_url, timeout=30)
        if response.status_code == 200:
            return True, ""
        else:
            return False, f"REST API returned status code {response.status_code}."
    except requests.exceptions.RequestException as e:
        return False, f"Could not connect to the REST API: {e}"


def fetch_all_pages(base_url, params, status_text, item_name, session):
    """Fetch all pages of a WordPress REST API endpoint."""
    all_items = []
    page = 1

    while True:
        params['page'] = page
        try:
            response = session.get(base_url, params=params, timeout=30)
            if response.status_code == 200:
                items = response.json()
                all_items.extend(items)

                total_pages = int(response.headers.get('X-WP-TotalPages', 1))
                status_text.text(f'Fetching {item_name}: Page {page}/{total_pages}')

                if page >= total_pages:
                    break
                else:
                    page += 1
            else:
                st.error(f'Error {response.status_code} while fetching {item_name} page {page}')
                break
        except requests.exceptions.RequestException as e:
            st.error(f'An error occurred while fetching {item_name}: {e}')
            break

    return all_items


def fetch_all_published_posts(base_site_url, status_text, session, categories_option, tags_option):
    """Fetch all published posts from the WordPress site."""
    base_url = f'{base_site_url}/wp-json/wp/v2/posts'
    fields = ['link', 'title', 'content', 'featured_media']
    if categories_option:
        fields.append('categories')
    if tags_option:
        fields.append('tags')
    params = {
        'status': 'publish',
        'per_page': 100,
        '_fields': ','.join(fields),
        '_embed': 'wp:featuredmedia',  # Include embedded media data
    }
    return fetch_all_pages(base_url, params, status_text, 'articles', session)


def fetch_all_categories(base_site_url, status_text, session):
    """Fetch all categories from the WordPress site."""
    base_url = f'{base_site_url}/wp-json/wp/v2/categories'
    params = {
        'per_page': 100,
    }
    categories = fetch_all_pages(base_url, params, status_text, 'categories', session)
    # Create a dictionary mapping category ID to name
    category_dict = {cat['id']: cat['name'] for cat in categories}
    status_text.text('All categories have been fetched.')
    return category_dict


def fetch_all_tags(base_site_url, status_text, session):
    """Fetch all tags from the WordPress site."""
    base_url = f'{base_site_url}/wp-json/wp/v2/tags'
    params = {
        'per_page': 100,
    }
    tags = fetch_all_pages(base_url, params, status_text, 'tags', session)
    # Create a dictionary mapping tag ID to name
    tag_dict = {tag['id']: tag['name'] for tag in tags}
    status_text.text('All tags have been fetched.')
    return tag_dict


def get_image_url(post, base_site_url, session):
    """Get image URL from embedded media or by fetching the media endpoint."""
    image_url = ''
    if post.get('featured_media'):
        # Try to get the image URL from embedded media
        embedded_media = post.get('_embedded', {}).get('wp:featuredmedia', [])
        if embedded_media and 'source_url' in embedded_media[0]:
            image_url = embedded_media[0]['source_url']
        else:
            # Fallback: Fetch the media data directly with retries
            media_id = post.get('featured_media')
            media_url = f"{base_site_url}/wp-json/wp/v2/media/{media_id}"
            try:
                response = session.get(media_url, timeout=30)
                if response.status_code == 200:
                    media_data = response.json()
                    image_url = media_data.get('source_url', '')
            except requests.exceptions.RequestException as e:
                st.warning(f"Failed to fetch media ID {media_id}: {e}")
    return image_url


def main():
    st.title('Fetching WordPress Posts via REST API')

    base_site_url = st.text_input('Enter the WordPress site URL (with http:// or https://)',
                                  'https://www.example.com')

    # Add sidebar options
    categories_option = st.sidebar.checkbox('Retrieve Categories', value=True)
    tags_option = st.sidebar.checkbox('Retrieve Tags', value=True)

    if st.button('Start fetching articles'):
        status_text = st.empty()
        # Validate the input URL
        is_valid_url, error_message = validate_wordpress_site(base_site_url)
        if not is_valid_url:
            st.error(f"URL Validation Error: {error_message}")
            return

        session = requests.Session()
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries)
        session.mount('http://', adapter)
        session.mount('https://', adapter)

        with st.spinner('Processing...'):
            try:
                # Fetch all published posts
                posts = fetch_all_published_posts(base_site_url, status_text, session, categories_option, tags_option)
                if not posts:
                    st.warning('No articles found.')
                    return
                st.success(f'Total articles fetched: {len(posts)}')

                # Fetch categories and tags if selected
                if categories_option:
                    category_dict = fetch_all_categories(base_site_url, status_text, session)
                else:
                    category_dict = {}
                if tags_option:
                    tag_dict = fetch_all_tags(base_site_url, status_text, session)
                else:
                    tag_dict = {}

                # Prepare to collect post data
                csv_data = []
                total_posts = len(posts)
                progress_bar = st.progress(0)

                for index, post in enumerate(posts, start=1):
                    # Update status and progress bar
                    status_text.text(f'Processing article {index}/{total_posts}')
                    progress_bar.progress(index / total_posts)

                    url = post.get('link', '')
                    title = post.get('title', {}).get('rendered', '')
                    content = post.get('content', {}).get('rendered', '')

                    # Get image URL from embedded media
                    image_url = get_image_url(post, base_site_url, session)

                    post_data = {
                        'url': url,
                        'title': title,
                        'content': content,
                        'image_url': image_url
                    }

                    # Handle categories if selected
                    if categories_option:
                        categories = []
                        category_ids = post.get('categories', [])
                        if category_ids:
                            categories = [category_dict.get(cat_id, 'Unknown') for cat_id in category_ids]
                        category_names = ', '.join(categories)
                        post_data['categories'] = category_names

                    # Handle tags if selected
                    if tags_option:
                        tags = []
                        tag_ids = post.get('tags', [])
                        if tag_ids:
                            tags = [tag_dict.get(tag_id, 'Unknown') for tag_id in tag_ids]
                        tag_names = ', '.join(tags)
                        post_data['tags'] = tag_names

                    csv_data.append(post_data)

                progress_bar.empty()
                status_text.text('Processing completed.')

                # Convert to DataFrame for display and download
                df = pd.DataFrame(csv_data)

                st.dataframe(df)

                # Button to download the CSV
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label='Download CSV file',
                    data=csv,
                    file_name='articles.csv',
                    mime='text/csv',
                )

            except Exception as e:
                st.error(f'An error occurred: {e}')


if __name__ == '__main__':
    main()
