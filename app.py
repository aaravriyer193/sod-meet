import uuid
import os
from flask import Flask, render_template, redirect, url_for, request, session, abort
from flask_socketio import SocketIO, emit, join_room
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'fallback-dev-key')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# --- OAUTH SETUP ---
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

# --- RESTRICTED ROOMS LOGIC ---
RESTRICTED_ROOMS = ['chairs', 'secretariat', 'interviews', 'jobless', 'safa', 'general', 'informal']
ALLOWED_EMAILS = os.getenv('ALLOWED_EMAILS', '').split(',')

# Track the Host of each room & user sessions
rooms_hosts = {}
user_sessions = {} 

@app.route('/login')
def login():
    redirect_uri = url_for('auth_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth/callback')
def auth_callback():
    token = google.authorize_access_token()
    user_info = token.get('userinfo')
    if user_info:
        session['user'] = user_info
    
    # Send them back to the room they tried to access
    next_url = session.pop('next_url', '/')
    return redirect(next_url)

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/join')
def create_room():
    room_id = f"{uuid.uuid4().hex[:3]}-{uuid.uuid4().hex[:4]}-{uuid.uuid4().hex[:3]}"
    return redirect(url_for('meeting', room_id=room_id))

@app.route('/<room_id>')
def meeting(room_id):
    # Security Check
    if room_id in RESTRICTED_ROOMS:
        if 'user' not in session:
            session['next_url'] = request.url
            return redirect(url_for('login'))
        if session['user']['email'] not in ALLOWED_EMAILS:
            return f"<h1>Access Denied</h1><p>Your email ({session['user']['email']}) is not authorized to join the <b>{room_id}</b> room.</p>", 403

    # Pass the Google name to the frontend if they are logged in
    user_name = session.get('user', {}).get('name', '')
    return render_template('index.html', room_id=room_id, user_name=user_name)

# --- WEBRTC & SOCKET LOGIC ---
@socketio.on('request-join')
def request_join(data):
    room = data['room']
    user_id = data['userId']
    name = data['name']
    
    user_sessions[request.sid] = {'room': room, 'userId': user_id}
    join_room(user_id) 
    
    if room not in rooms_hosts or rooms_hosts[room] is None:
        rooms_hosts[room] = user_id
        emit('join-accepted', {'isHost': True}, to=user_id)
    else:
        host_id = rooms_hosts[room]
        emit('join-request', {'userId': user_id, 'name': name}, to=host_id)

@socketio.on('admit-user')
def admit_user(data):
    emit('join-accepted', {'isHost': False}, to=data['target'])

@socketio.on('deny-user')
def deny_user(data):
    emit('join-denied', {}, to=data['target'])

@socketio.on('join-room')
def on_join(data):
    room = data['room']
    user_id = data['userId']
    name = data['name']
    user_sessions[request.sid] = {'room': room, 'userId': user_id}
    join_room(room)
    emit('user-joined', {'userId': user_id, 'name': name}, to=room, include_self=False)

@socketio.on('signal')
def handle_signal(data):
    emit('signal', data, to=data['target'])

@socketio.on('chat-msg')
def handle_chat(data):
    emit('chat-msg', data, to=data['room'])

@socketio.on('admin-action')
def handle_admin(data):
    emit('admin-action', data, to=data['target'])

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in user_sessions:
        room = user_sessions[sid]['room']
        user_id = user_sessions[sid]['userId']
        
        if room in rooms_hosts and rooms_hosts[room] == user_id:
            emit('meeting-ended', {}, to=room)
            rooms_hosts.pop(room, None)
        
        user_sessions.pop(sid, None)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
