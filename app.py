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

# manage_session=False ensures Flask and SocketIO share the Google Login session perfectly
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', manage_session=False)

# --- OAUTH SETUP ---
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

# --- SECURITY & VIP LOGIC ---
RESTRICTED_ROOMS = ['secretariat']

# These users will ALWAYS become Host in any room, and are the ONLY allowed hosts in /interviews
VIP_EMAILS = [
    'shahvishesh2009@gmail.com', 
    'sg.sodmun@gmail.com', 
    'sg.sodmun.com', 
    'ramp31282@gmail.com', 
    'dhairyakamlani09@gmail.com', 
    'nandaniyamat@gmail.com', 
    'aaravmamtani74@gmail.com', 
    'aashi.rayan123@gmail.com'
]

raw_emails = os.getenv('ALLOWED_EMAILS', '').split(',')
ALLOWED_EMAILS = [email.strip().lower() for email in raw_emails if email.strip()]

# Bulletproof JSON-Style State Management
active_rooms = {}  
# Format: {'room_id': {'host': 'user_id', 'host_email': 'email', 'participants': {'sid': 'user_id'}, 'waiting': {'user_id': {'name': 'name'}}}}
user_sessions = {} 
# Format: {'sid': {'room': 'room_id', 'userId': 'user_id', 'name': 'name', 'email': 'email'}}

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
    # SANITIZATION: Forces all links into the exact same parallel universe
    room_id = room_id.strip().lower()

    if 'user' not in session:
        session['next_url'] = request.url
        return redirect(url_for('login'))
        
    user_email = session['user'].get('email', '').strip().lower()
    is_vip = user_email in VIP_EMAILS

    # Hard Block for restricted rooms
    if room_id in RESTRICTED_ROOMS:
        if not is_vip and user_email not in ALLOWED_EMAILS:
            return f"""
            <html>
            <head><title>Access Denied</title><link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700&display=swap" rel="stylesheet"></head>
            <body style="background:#0f0f11; color:white; font-family:'Nunito', sans-serif; display:flex; align-items:center; justify-content:center; height:100vh; margin:0;">
                <div style="background:#1a1a1e; padding:40px; border-radius:24px; border:1px solid rgba(234,67,53,0.3); text-align:center; box-shadow:0 20px 50px rgba(0,0,0,0.8); max-width: 400px;">
                    <div style="font-size: 50px; margin-bottom: 10px;">🔒</div>
                    <h1 style="color:#ea4335; margin-top:0;">Access Denied</h1>
                    <p style="color:#aaa; font-size:1.1rem; line-height: 1.5;">The account <b>{user_email}</b> lacks clearance for <b>/{room_id}</b>.</p>
                    <button onclick="window.location.href='/'" style="background:#FF8C00; color:black; border:none; padding:12px 25px; border-radius:10px; font-weight:bold; cursor:pointer; margin-top:20px; font-size:1rem; width: 100%;">Return</button>
                </div>
            </body>
            </html>
            """, 403

    user_name = session.get('user', {}).get('name', '')
    return render_template('index.html', room_id=room_id, user_name=user_name)

# --- WEBRTC & SOCKET LOGIC ---
@socketio.on('request-join')
def request_join(data):
    room = data['room'].strip().lower()
    user_id = data['userId']
    name = data['name']
    sid = request.sid
    
    # Grab the user's email directly from their Google Login session to prevent spoofing
    user_email = session.get('user', {}).get('email', '').strip().lower()
    is_vip = user_email in VIP_EMAILS
    
    # Initialize room memory if it doesn't exist
    if room not in active_rooms:
        active_rooms[room] = {'host': None, 'host_email': None, 'participants': {}, 'waiting': {}}
    
    user_sessions[sid] = {'room': room, 'userId': user_id, 'name': name, 'email': user_email}
    join_room(user_id) # Temporary personal room for direct signaling
    
    current_host = active_rooms[room]['host']
    current_host_email = active_rooms[room]['host_email']

    become_host = False
    usurp_host = False

    # HOST ASSIGNMENT LOGIC
    if current_host is None:
        # If the room is empty, they become host... UNLESS it's interviews and they aren't a VIP.
        if room == 'interviews' and not is_vip:
            become_host = False 
        else:
            become_host = True
    else:
        # Room is not empty. If joining user is a VIP, and current host is NOT a VIP, usurp them.
        if is_vip and current_host_email not in VIP_EMAILS:
            become_host = True
            usurp_host = True

    if become_host:
        # Tell the old host they have been demoted
        if usurp_host and current_host:
            emit('admin-action', {'action': 'demote-host'}, to=current_host)
            
        # Crown the new VIP Host
        active_rooms[room]['host'] = user_id
        active_rooms[room]['host_email'] = user_email
        emit('join-accepted', {'isHost': True}, to=user_id)
        
        # CRITICAL: Forward anyone who was stuck in the waiting room to the new VIP Host!
        for w_uid, w_data in list(active_rooms[room]['waiting'].items()):
            emit('join-request', {'userId': w_uid, 'name': w_data['name']}, to=user_id)
            
    else:
        # They are a normal user requesting to join
        if active_rooms[room]['host']:
            emit('join-request', {'userId': user_id, 'name': name}, to=active_rooms[room]['host'])
        else:
            # If they join /interviews and no VIP is there yet, they are quietly buffered in memory
            active_rooms[room]['waiting'][user_id] = {'name': name}

@socketio.on('admit-user')
def admit_user(data):
    target_id = data['target']
    sid = request.sid
    room = user_sessions.get(sid, {}).get('room')
    
    # Remove from waiting buffer
    if room and target_id in active_rooms.get(room, {}).get('waiting', {}):
        del active_rooms[room]['waiting'][target_id]
        
    emit('join-accepted', {'isHost': False}, to=target_id)

@socketio.on('deny-user')
def deny_user(data):
    target_id = data['target']
    sid = request.sid
    room = user_sessions.get(sid, {}).get('room')
    
    if room and target_id in active_rooms.get(room, {}).get('waiting', {}):
        del active_rooms[room]['waiting'][target_id]
        
    emit('join-denied', {}, to=target_id)

@socketio.on('join-room')
def on_join(data):
    room = data['room'].strip().lower()
    user_id = data['userId']
    name = data['name']
    sid = request.sid
    
    join_room(room) # Locks them into the strict WebRTC tunnel
    if room in active_rooms:
        active_rooms[room]['participants'][sid] = user_id

    emit('user-joined', {'userId': user_id, 'name': name}, to=room, include_self=False)

@socketio.on('signal')
def handle_signal(data):
    emit('signal', data, to=data['target'])

@socketio.on('chat-msg')
def handle_chat(data):
    # STRICT TUNNELING: Prevents Chat Parallel Universes
    room = data.get('room', '').strip().lower()
    emit('chat-msg', data, to=room)

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
        
        if room in active_rooms:
            # Remove from waiting buffer if they dropped out early
            if user_id in active_rooms[room]['waiting']:
                del active_rooms[room]['waiting'][user_id]
                
            # Remove from active participants
            if sid in active_rooms[room]['participants']:
                del active_rooms[room]['participants'][sid]
                
                # If the HOST leaves, securely pick a new host
                if active_rooms[room]['host'] == user_id:
                    new_host_id = None
                    new_host_email = None
                    
                    for p_sid, p_uid in active_rooms[room]['participants'].items():
                        p_email = user_sessions.get(p_sid, {}).get('email', '')
                        
                        if room == 'interviews':
                            # Only promote remaining VIPs in the interviews room
                            if p_email in VIP_EMAILS:
                                new_host_id = p_uid
                                new_host_email = p_email
                                break
                        else:
                            # Promote anyone in normal rooms
                            new_host_id = p_uid
                            new_host_email = p_email
                            break
                            
                    active_rooms[room]['host'] = new_host_id
                    active_rooms[room]['host_email'] = new_host_email
                    
                    if new_host_id:
                        emit('admin-action', {'action': 'make-host'}, to=new_host_id)
        
        # Tell everyone in the room to strictly delete this user's video element
        emit('user-left', {'userId': user_id}, to=room)
        leave_room(room)
        del user_sessions[sid]

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
