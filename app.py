import uuid
from flask import Flask, render_template, redirect, url_for, request
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'sodmeet-ultra-premium'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Track the Host of each room
rooms_hosts = {}
# Track which user/room belongs to which active socket connection
user_sessions = {} 

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/join')
def create_room():
    room_id = f"{uuid.uuid4().hex[:3]}-{uuid.uuid4().hex[:4]}-{uuid.uuid4().hex[:3]}"
    return redirect(url_for('meeting', room_id=room_id))

@app.route('/<room_id>')
def meeting(room_id):
    return render_template('index.html', room_id=room_id)

@socketio.on('request-join')
def request_join(data):
    room = data['room']
    user_id = data['userId']
    name = data['name']
    
    # Register the session so we know who they are if they disconnect
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
    # Double check session registration
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

# --- THE HOST CLEANUP LOGIC ---
@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in user_sessions:
        room = user_sessions[sid]['room']
        user_id = user_sessions[sid]['userId']
        
        # If the person who just disconnected was the Host, nuke the room
        if room in rooms_hosts and rooms_hosts[room] == user_id:
            emit('meeting-ended', {}, to=room)
            rooms_hosts.pop(room, None)
        
        user_sessions.pop(sid, None)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
