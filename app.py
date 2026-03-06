import uuid
from flask import Flask, render_template, redirect, url_for
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'sodmeet-ultra-premium'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

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
    
    # Join the main meeting room (for chat)
    join_room(room)
    # CRITICAL FIX: Join a private room for this specific user (for WebRTC signals)
    join_room(user_id) 
    
    emit('user-joined', {'userId': user_id, 'name': name}, to=room, include_self=False)

@socketio.on('signal')
def handle_signal(data):
    # Now this will successfully target the specific user's private room
    emit('signal', data, to=data['target'])

@socketio.on('chat-msg')
def handle_chat(data):
    emit('chat-msg', data, to=data['room'])

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)