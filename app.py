from flask import Flask, render_template, request, redirect, url_for, jsonify, session # Import session
import requests
import time
import os
import musicbrainzngs
import musicbrainzngs.musicbrainz
from musicbrainzngs.musicbrainz import WebServiceError

# TODO: "Clear All" button
app = Flask(__name__)
# --- IMPORTANT: Flask Session requires a secret key ---
# Change this to a random, complex string in production!
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'a_very_secret_and_random_key_for_dev')

# --- Configuration Keys for Session ---
API_KEY_SESSION_KEY = 'maloja_api_key'
BASE_URL_SESSION_KEY = 'maloja_base_url'


# --- Default Configuration (used if nothing is set in session) ---
DEFAULT_MALOJA_API_KEY = ""
DEFAULT_MALOJA_BASE_URL = ""


# --- Helper function to get current config ---
def get_maloja_config():
    """Retrieves the Maloja API key and base URL from the session, with fallbacks."""
    api_key = session.get(API_KEY_SESSION_KEY, DEFAULT_MALOJA_API_KEY)
    base_url = session.get(BASE_URL_SESSION_KEY, DEFAULT_MALOJA_BASE_URL)
    # Construct the full URL with the key
    full_url = f"{base_url}/apis/mlj_1/newscrobble?key={api_key}"
    return api_key, base_url, full_url


# --- MusicBrainz Configuration ---
# MusicBrainz requires a user agent string
# Replace with your app name, version, and a contact email/website
musicbrainzngs.set_useragent(
    "Maloja Manual Scrobbler App",
    "0.1",
    "your.email@example.com" # Or a URL
)

# --- Main Scrobble Form Route ---
@app.route('/', methods=['GET', 'POST'])
def index():
    message = None
    status = None # 'success' or 'error'
    last_artist = None
    last_title = None
    last_album = None
    batch_results = None  # To store results from batch upload

    # Get current configuration
    api_key, base_url, maloja_api_full_url = get_maloja_config()

    if api_key == "" or base_url == "":
        message = "Please set your Maloja API key and URL in the Options."
        status = "warning"

    if request.method == 'POST':
        # Check if this is a regular form submission or a file upload
        if 'scrobble_file' in request.files:
            # This is a file upload request
            # Logic will be handled in the /upload_scrobble_log route
            # This part of index() will not execute for file uploads as they go to a different endpoint
            pass
        else:
            # This is a regular single scrobble form submission
            last_artist = request.form.get('artist')
            last_title = request.form.get('title')
            last_album = request.form.get('album')

            if not last_artist or not last_title or not last_album:
                message = "Error: Artist, Title, and Album are required for single scrobble."
                status = "error"
            else:
                timestamp = int(time.time())
                payload = {
                    "artist": last_artist,
                    "title": last_title,
                    "album": last_album,
                    "time": timestamp
                }

                try:
                    response = requests.post(maloja_api_full_url, json=payload)
                    response.raise_for_status()

                    message = "Single scrobble successful!"
                    status = "success"

                except requests.exceptions.RequestException as e:
                    message = f"Single scrobble failed: {e}"
                    status = "error"
                    if 'response' in locals() and response is not None:
                        message += f" | Status Code: {response.status_code}"
                        try:
                            error_details = response.json()
                            message += f" | Details: {error_details}"
                        except requests.exceptions.JSONDecodeError:
                            message += f" | Response Body: {response.text}"


    # Render the template again, but this time with the message and last entered values
    return render_template('form.html', message=message, status=status,
                           last_artist=last_artist, last_title=last_title, last_album=last_album)


# --- Options Page Route ---
@app.route('/options', methods=['GET', 'POST'])
def options():
    message = None
    status = None

    if request.method == 'POST':
        # Get data from the form
        new_api_key = request.form.get('api_key')
        new_base_url = request.form.get('base_url')

        # Save to session
        session[API_KEY_SESSION_KEY] = new_api_key
        session[BASE_URL_SESSION_KEY] = new_base_url

        message = "Configuration saved successfully!"
        status = "success"

        # Optional: Redirect back to the form page after saving
        # return redirect(url_for('index'))

    # For GET request or after POST (if not redirected), display the form
    # Retrieve current values from session to pre-fill the form
    current_api_key = session.get(API_KEY_SESSION_KEY, '') # Use empty string if not set
    current_base_url = session.get(BASE_URL_SESSION_KEY, '')

    return render_template('options.html',
                           current_api_key=current_api_key,
                           current_base_url=current_base_url,
                           message=message,
                           status=status)


# --- Uploading Scrobble Log File ---
@app.route('/upload_scrobble_log', methods=['POST'])
def upload_scrobble_log():
    if 'scrobble_file' not in request.files:
        return render_template('form.html', message="No file part in the request.", status="error")

    file = request.files['scrobble_file']

    if file.filename == '':
        return render_template('form.html', message="No selected file.", status="error")

    if file:
        # Get current configuration for Maloja API
        api_key, base_url, maloja_api_full_url = get_maloja_config()

        # Check if config is set
        if not api_key or not base_url:  # simplified check, could be more robust
            return render_template('form.html',
                                   message="Maloja API configuration is missing. Please set it in Options.",
                                   status="error")

        # Read file content
        file_content = file.read().decode('utf-8')
        lines = file_content.splitlines()

        scrobble_results = []
        scrobble_count = 0
        success_count = 0
        error_count = 0
        warning_count = 0

        # Skip header lines (starting with #) and process data lines
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue  # Skip empty lines and comments/headers

            # Split by tab delimiter
            parts = line.split('\t')

            # Ensure we have enough parts for the required data
            # ARTIST #ALBUM #TITLE #TRACKNUM #LENGTH #RATING #TIMESTAMP #MUSICBRAINZ_TRACKID
            # 0      1      2       3          4       5       6           7
            if len(parts) >= 7:
                artist = parts[0].strip()
                album = parts[1].strip()
                title = parts[2].strip()
                timestamp_str = parts[6].strip()

                # Basic validation for timestamp
                try:
                    timestamp = int(timestamp_str)
                except ValueError:
                    scrobble_results.append({
                        "artist": artist, "title": title,
                        "status": "failed", "message": f"Invalid timestamp: {timestamp_str}"
                    })
                    error_count += 1
                    continue  # Skip to next line

                scrobble_count += 1

                # Important for anyone who isn't me!!!
                # Eastern Time Offset Correction because I can't set a timezone on Rockbox.
                timestamp = timestamp + (4 * 3600)

                payload = {
                    "artist": artist,
                    "album": album,
                    "title": title,
                    "time": timestamp
                }


                try:
                    response = requests.post(maloja_api_full_url, json=payload, timeout=10)  # Add timeout
                    response.raise_for_status()

                    # Find "scrobble_exists" warnings and alert user.
                    response_json = {}
                    try:
                        response_json = response.json()
                    except requests.exceptions.JSONDecodeError:
                        print(f"Warning: Could not decode JSON from successful response for {artist} - {title}. Response text: {response.text}")
                        # but it did work!
                        scrobble_results.append({
                            "artist": artist, "title": title,
                            "status": "success", "message": "Scrobble successful (non-JSON response)."
                        })
                        success_count += 1
                        continue # Move to next scrobble

                    if response_json.get('status') == 'success':
                        message_status = "Scrobble successful!"
                        result_status = "success"

                        warnings = response_json.get('warnings', [])
                        for warning in warnings:
                            if warning.get('type') == 'scrobble_exists':
                                message_status = "Scrobble already exists! (skipped)"
                                result_status = "warning"
                                warning_count += 1
                                break

                        scrobble_results.append({
                            "artist": artist, "title": title,
                            "status": result_status, "message": message_status
                        })
                        # if no warnings, then tally success
                        if result_status == "success":
                            success_count += 1
                    else:
                        error_message = f"API reported non-successful scrobble status: {response_json.get('desc', response_json)}"
                        scrobble_results.append({
                            "artist": artist, "title": title,
                            "status": "failed", "message": error_message
                        })
                        error_count += 1


                except requests.exceptions.RequestException as e:
                    error_message = f"API Error: {e}"
                    if hasattr(e, 'response') and e.response is not None:
                        error_message += f" (Status: {e.response.status_code})"
                        try:
                            error_details = e.response.json()
                            error_message += f" Details: {error_details}"
                        except requests.exceptions.JSONDecodeError:
                            error_message += f" Body: {e.response.text}"
                    scrobble_results.append({
                        "artist": artist, "title": title,
                        "status": "failed", "message": error_message
                    })
                    error_count += 1
            else:
                scrobble_results.append({
                    "artist": "N/A", "title": line,
                    "status": "failed", "message": "Insufficient data fields on line."
                })
                error_count += 1

        summary_message = f"Processed {scrobble_count} scrobbles: {success_count} succeeded, {error_count} failed."

        return render_template('form.html', message=summary_message, status="info",
                               batch_results=scrobble_results)

    return render_template('form.html', message="An unexpected error occurred during file upload.", status="error")


# --- MusicBrainz Search Endpoints ---

@app.route('/search/artist')
def search_artist():
    query = request.args.get('term', '') # Get the search term from the frontend
    if not query:
        return jsonify([]) # Return empty list if no query

    try:
        # Search MusicBrainz for artists
        # limit=10 to keep results manageable
        result = musicbrainzngs.search_artists(query, limit=10)
        artists = result.get('artist-list', [])

        formatted_results = []
        for artist in artists:
            name = artist.get('name', 'Unknown Artist')
            disambiguation = artist.get('disambiguation')
            label = name
            if disambiguation:
                label = f"{name} ({disambiguation})"
            # No MBID needed for artist search results for this feature
            formatted_results.append({'label': label, 'value': name})

        return jsonify(formatted_results)

    except WebServiceError as e: # Use imported WebServiceError
        print(f"MusicBrainz API error (search_artist): {e}")
        return jsonify([]), 500


@app.route('/search/album')
def search_album():
    query = request.args.get('term', '')
    artist_name = request.args.get('artist', '') # Get the artist name sent from the frontend

    if not query and not artist_name: # Only return empty if both are empty
        return jsonify([])

    # Build the MusicBrainz query string using Lucene syntax
    # We'll search for releases (albums) where the title matches 'query'
    # AND the artist credit name matches 'artist_name' (if provided)
    mb_query_parts = [f'release:"{query}"'] # Start with the album title search

    if artist_name:
        # Add the artist filter. Escape any quotes in the artist name.
        escaped_artist = artist_name.replace('"', '\\"')
        mb_query_parts.append(f'artistname:"{escaped_artist}"') # Use artistname field for credit name


    # Join the parts with AND
    mb_query = ' AND '.join(mb_query_parts)

    # If query was empty but artist_name exists, mb_query might be just artistname:"...",
    # which is valid. If artist_name was also empty, mb_query might be just release:"", which is also valid.

    print(f"Searching MusicBrainz Releases with query: {mb_query}") # For debugging

    try:
        # Search MusicBrainz for releases (albums) using the constructed query
        result = musicbrainzngs.search_releases(mb_query, limit=10)
        releases = result.get('release-list', [])

        formatted_results = []
        for release in releases:
            # --- IMPORTANT: Include the MBID in the result ---
            mbid = release.get('id')
            if not mbid: # Skip results without an MBID (shouldn't happen often for releases)
                 continue

            title = release.get('title', 'Unknown Album')
            # Get the main artist credit name
            artist_credits = release.get('artist-credit', [])
            artist = artist_credits[0].get('name', 'Various Artists') if artist_credits else 'Various Artists'
            year = release.get('date', '')[:4] # Get just the year if date exists
            disambiguation = release.get('disambiguation')

            label = f"{title} by {artist}"
            if year:
                label += f" ({year})"
            if disambiguation:
                 label += f" ({disambiguation})"

            # Add the mbid to the dictionary
            formatted_results.append({'label': label, 'value': title, 'mbid': mbid})

        return jsonify(formatted_results)

    except WebServiceError as e: # Use imported WebServiceError
        print(f"MusicBrainz API error (search_album): {e}")
        return jsonify([]), 500


@app.route('/search/title')
def search_title():
    # It doesn't need the MBID for this feature, only the album/artist names for filtering.
    query = request.args.get('term', '')
    artist_name = request.args.get('artist', '') # Get artist name
    album_name = request.args.get('album', '') # Get album name

    if not query and not artist_name and not album_name: # Return empty if all are empty
        return jsonify([])

    mb_query_parts = [f'recording:"{query}"'] # Start with the track title search

    if artist_name:
        escaped_artist = artist_name.replace('"', '\\"')
        mb_query_parts.append(f'artistname:"{escaped_artist}"') # Filter by artist credit name

    if album_name:
        escaped_album = album_name.replace('"', '\\"')
        mb_query_parts.append(f'release:"{escaped_album}"') # Filter recordings by release title


    mb_query = ' AND '.join(mb_query_parts)

    print(f"Searching MusicBrainz Recordings with query: {mb_query}") # For debugging

    try:
        result = musicbrainzngs.search_recordings(mb_query, limit=10)
        recordings = result.get('recording-list', [])

        formatted_results = []
        for recording in recordings:
            title = recording.get('title', 'Unknown Title')
            artist_credits = recording.get('artist-credit', [])
            artist = artist_credits[0].get('name', 'Various Artists') if artist_credits else 'Various Artists'
            disambiguation = recording.get('disambiguation')

            label = f"{title} by {artist}"
            if disambiguation:
                 label += f" ({disambiguation})"

            formatted_results.append({'label': label, 'value': title})

        return jsonify(formatted_results)

    except WebServiceError as e: # Use imported WebServiceError
        print(f"MusicBrainz API error (search_title): {e}")
        return jsonify([]), 500


@app.route('/get_cover_art/<mbid>')
def get_cover_art(mbid):
    if not mbid:
        return jsonify({'imageUrl': None}), 400 # Bad request if no MBID

    try:
        # Use get_image_list to get the list of cover art images for the release MBID
        # This function returns a dictionary with an 'images' key containing a list of image dictionaries
        cover_art_list_data = musicbrainzngs.get_image_list(mbid)

        image_url = None
        # Look for an approved front image
        if 'images' in cover_art_list_data:
            for image in cover_art_list_data['images']:
                # Check if it's a 'Front' image and is approved
                if 'Front' in image.get('types', []) and image.get('approved', False):
                    # Get the URL for the 'large' thumbnail if available, otherwise the main 'image' URL
                    image_url = image.get('thumbnails', {}).get('large', image.get('image'))
                    if image_url:
                        break # Found the front cover, stop searching

        if image_url:
            # MusicBrainz cover art URLs don't always have a scheme (http/https)
            # Ensure it's a full URL by adding https if missing
            if not image_url.startswith('http'):
                 image_url = 'https:' + image_url

            return jsonify({'imageUrl': image_url})
        else:
            # No approved front image found in the list
            print(f"No approved front cover art found in CAA for MBID: {mbid}")
            return jsonify({'imageUrl': None}), 404 # Not Found

    # get_image_list can raise WebServiceError
    except WebServiceError as e: # Use imported WebServiceError
        # This might also catch cases where the MBID is not found in MusicBrainz/CAA
        print(f"MusicBrainz API error (get_cover_art) for MBID {mbid}: {e}")
        # Check if the error indicates the release wasn't found (e.g., 404 status code)
        if hasattr(e, 'cause') and hasattr(e.cause, 'code') and e.cause.code == 404:
             print(f"MBID {mbid} not found in MusicBrainz/CAA.")
             return jsonify({'imageUrl': None}), 404 # Not Found
        else:
             return jsonify({'imageUrl': None}), 500 # Internal Server Error

    # Catch any other unexpected errors
    except Exception as e:
        print(f"Unexpected error in get_cover_art for MBID {mbid}: {e}")
        return jsonify({'imageUrl': None}), 500


if __name__ == '__main__':
    # Run the Flask development server
    # Use host='0.0.0.0' to make it accessible from other devices on your network
    app.run(debug=True)
