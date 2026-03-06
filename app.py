import uuid
from flask import Flask, render_template, redirect, url_for
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'sodmeet-ultra-premium'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Dictionary to track who is the Host of each room
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

@socketio.on('join-room')
def on_join(data):
    room = data['room']
    user_id = data['userId']
    name = data['name']
    
    join_room(room)
    join_room(user_id) 

    # Admin Logic: If the room doesn't have a host yet, this user becomes the host
    is_host = False
    if room not in rooms_hosts:
        rooms_hosts[room] = user_id
        is_host = True

    # Tell the user if they are the host or not
    emit('room-joined', {'isHost': is_host}, to=user_id)
    emit('user-joined', {'userId': user_id, 'name': name}, to=room, include_self=False)

@socketio.on('signal')
def handle_signal(data):
    emit('signal', data, to=data['target'])

@socketio.on('chat-msg')
def handle_chat(data):
    emit('chat-msg', data, to=data['room'])

# New route for Admin kicks and mutes
@socketio.on('admin-action')
def handle_admin(data):
    # Sends the command specifically to the target user's private room
    emit('admin-action', data, to=data['target'])

@socketio.on('disconnect')
def test_disconnect():
    # In a full production app, you'd want logic here to assign a new host 
    # if the original host leaves the room.
    pass

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
