import uuid
import os
from flask import Flask, render_template, redirect, url_for, request, session, abort
from flask_socketio import SocketIO, emit, join_room, leave_room
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

# --- SECURITY & ROOMS LOGIC ---
RESTRICTED_ROOMS = ['chairs', 'secretariat', 'interviews', 'jobless', 'safa', 'general', 'informal']
MASTER_ADMIN = 'sg.sodmun@gmail.com'

raw_emails = os.getenv('ALLOWED_EMAILS', '').split(',')
ALLOWED_EMAILS = [email.strip().lower() for email in raw_emails if email.strip()]

# JSON-Style State Management
active_rooms = {}  # Format: {'room_id': {'host': 'user_id', 'participants': {'sid': 'user_id'}}}
user_sessions = {} # Format: {'sid': {'room': 'room_id', 'userId': 'user_id', 'name': 'name'}}

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
    
    next_url = session.pop('next_url', '/')
    return redirect(next_url)

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/join')
def create_room():
    if 'user' not in session:
        session['next_url'] = url_for('create_room')
        return redirect(url_for('login'))
        
    room_id = f"{uuid.uuid4().hex[:3]}-{uuid.uuid4().hex[:4]}-{uuid.uuid4().hex[:3]}"
    return redirect(url_for('meeting', room_id=room_id))

@app.route('/<room_id>')
def meeting(room_id):
    if 'user' not in session:
        session['next_url'] = request.url
        return redirect(url_for('login'))
        
    user_email = session['user'].get('email', '').strip().lower()

    if room_id in RESTRICTED_ROOMS:
        if user_email != MASTER_ADMIN and user_email not in ALLOWED_EMAILS:
            return f"""
            <html>
            <head><title>Access Denied</title><link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700&display=swap" rel="stylesheet"></head>
            <body style="background:#0f0f11; color:white; font-family:'Nunito', sans-serif; display:flex; align-items:center; justify-content:center; height:100vh; margin:0;">
                <div style="background:#1a1a1e; padding:40px; border-radius:24px; border:1px solid rgba(234,67,53,0.3); text-align:center; box-shadow:0 20px 50px rgba(0,0,0,0.8); max-width: 400px;">
                    <div style="font-size: 50px; margin-bottom: 10px;">🔒</div>
                    <h1 style="color:#ea4335; margin-top:0;">Access Denied</h1>
                    <p style="color:#aaa; font-size:1.1rem; line-height: 1.5;">The account <b>{user_email}</b> lacks clearance for <b>/{room_id}</b>.</p>
                    <button onclick="window.location.href='/'" style="background:#FF8C00; color:black; border:none; padding:12px 25px; border-radius:10px; font-weight:bold; cursor:pointer; margin-top:20px; font-size:1rem; width: 100%;">Return to Dashboard</button>
                </div>
            </body>
            </html>
            """, 403

    user_name = session.get('user', {}).get('name', '')
    return render_template('index.html', room_id=room_id, user_name=user_name)

# --- WEBRTC & SOCKET LOGIC ---
@socketio.on('request-join')
def request_join(data):
    room = data['room']
    user_id = data['userId']
    name = data['name']
    sid = request.sid
    
    # Initialize room in JSON state if it doesn't exist
    if room not in active_rooms:
        active_rooms[room] = {'host': user_id, 'participants': {}}
    
    user_sessions[sid] = {'room': room, 'userId': user_id, 'name': name}
    join_room(user_id) # Temporary personal room for direct signaling
    
    # If room is empty or they are the first one, they become host automatically
    if not active_rooms[room]['participants']:
        active_rooms[room]['host'] = user_id
        emit('join-accepted', {'isHost': True}, to=user_id)
    else:
        # Ask current host for permission
        host_id = active_rooms[room]['host']
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
    sid = request.sid
    
    join_room(room)
    if room in active_rooms:
        active_rooms[room]['participants'][sid] = user_id

    # Broadcast to everyone else that a new peer has arrived
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
        user_data = user_sessions[sid]
        room = user_data['room']
        user_id = user_data['userId']
        
        # Remove from active rooms JSON
        if room in active_rooms and sid in active_rooms[room]['participants']:
            del active_rooms[room]['participants'][sid]
            
            # If the host leaves, randomly assign a new host if people are still there
            if active_rooms[room]['host'] == user_id:
                if active_rooms[room]['participants']:
                    new_host_sid = list(active_rooms[room]['participants'].keys())[0]
                    new_host_id = active_rooms[room]['participants'][new_host_sid]
                    active_rooms[room]['host'] = new_host_id
                    emit('admin-action', {'action': 'make-host'}, to=new_host_id)
                else:
                    del active_rooms[room] # Room is empty, destroy it
        
        # Tell everyone in the room to strictly delete this user's video element
        emit('user-left', {'userId': user_id}, to=room)
        leave_room(room)
        del user_sessions[sid]

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
