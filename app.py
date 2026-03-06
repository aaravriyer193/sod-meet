import uuid
from flask import Flask, render_template, redirect, url_for
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'sodmeet-ultra-premium'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Dictionary to track the Host of each room
rooms_hosts = {}

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

# 1. WAITING ROOM LOGIC
@socketio.on('request-join')
def request_join(data):
    room = data['room']
    user_id = data['userId']
    name = data['name']
    
    join_room(user_id) # Private room for this specific user
    
    if room not in rooms_hosts or rooms_hosts[room] is None:
        # First person to join automatically becomes the Host
        rooms_hosts[room] = user_id
        emit('join-accepted', {'isHost': True}, to=user_id)
    else:
        # Send a request to the Host to admit this user
        host_id = rooms_hosts[room]
        emit('join-request', {'userId': user_id, 'name': name}, to=host_id)

@socketio.on('admit-user')
def admit_user(data):
    emit('join-accepted', {'isHost': False}, to=data['target'])

@socketio.on('deny-user')
def deny_user(data):
    emit('join-denied', {}, to=data['target'])

# 2. STANDARD MEETING LOGIC
@socketio.on('join-room')
def on_join(data):
    # This is only called AFTER the host admits them
    room = data['room']
    user_id = data['userId']
    name = data['name']
    join_room(room)
    emit('user-joined', {'userId': user_id, 'name': name}, to=room, include_self=False)

@socketio.on('signal')
def handle_signal(data):
    emit('signal', data, to=data['target'])

@socketio.on('chat-msg')
def handle_chat(data):
    emit('chat-msg', data, to=data['room'])

# 3. ADMIN POWERS
@socketio.on('admin-action')
def handle_admin(data):
    emit('admin-action', data, to=data['target'])

@socketio.on('disconnect')
def test_disconnect():
    # Production apps handle host migration here if the host drops
    pass

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
