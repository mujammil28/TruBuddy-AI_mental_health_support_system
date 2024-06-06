from flask import Flask, request, jsonify, session
import google.generativeai as genai
from flask_cors import CORS
import mysql.connector
import secrets
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer

app = Flask(__name__)
cors = CORS(app, resources={r"/*": {"origins": "*"}})
app.secret_key = "mysecret"

# System instructions for generative AI models
system_instruction = "Your name is TRU Buddy and you are a cute mental health chatbot and help users to fully recover\n\n"
system_instruction1 = "Your name is TRU Buddy and you are a cute mental health therapist who analyzes the score of Mental Health Assessments and gives suggestions based on this\n\n"

# Set up Gemini API client
genai.configure(api_key="AIzaSyCrYx7XrOVICwjhWiQvYhqR5aMp3LHB9L0")
model = genai.GenerativeModel('gemini-1.5-pro-latest', system_instruction=system_instruction)
model2 = genai.GenerativeModel('gemini-1.5-pro-latest', system_instruction=system_instruction1)

# Download nltk data
nltk.download('punkt')
nltk.download('vader_lexicon')

# Initialize Sentiment Analyzer
sid = SentimentIntensityAnalyzer()

# Database connection details
db_config = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "TRUBUDDY",
    "buffered": True,
}

def create_tables():
    try:
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                email VARCHAR(255) UNIQUE,
                password VARCHAR(255),
                full_name VARCHAR(255),
                mobile VARCHAR(15)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversation (
                id INT AUTO_INCREMENT PRIMARY KEY,
                message TEXT,
                role ENUM('user', 'bot')
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exercise (
                id INT AUTO_INCREMENT PRIMARY KEY,
                exercise_title VARCHAR(255),
                exercise_name VARCHAR(255),
                exercise_description TEXT,
                video_link VARCHAR(255)
            )
        """)
        connection.commit()
        cursor.close()
        connection.close()
    except mysql.connector.Error as e:
        print(f"Error creating tables: {e}")

create_tables()

def store_message_in_db(message, role):
    try:
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        cursor.execute("INSERT INTO conversation (message, role) VALUES (%s, %s)", (message, role))
        connection.commit()
        cursor.close()
        connection.close()
    except mysql.connector.Error as e:
        print(f"Error storing message in database: {e}")

def get_conversation_history_from_db():
    try:
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        cursor.execute("SELECT message, role FROM conversation ORDER BY id")
        conversation_history = [{'role': row[1], 'content': row[0]} for row in cursor.fetchall()]
        cursor.close()
        connection.close()
        return conversation_history
    except mysql.connector.Error as e:
        print(f"Error retrieving conversation history from database: {e}")
        return []

def get_db_connection():
    try:
        connection = mysql.connector.connect(**db_config)
        return connection
    except mysql.connector.Error as e:
        print(f"Error connecting to database: {e}")
        return None

def classify_user_input(message):
    greetings = ["hello", "hi", "hey", "how are you", "good morning", "good afternoon", "good evening"]
    negative_responses = ["don't help", "im fine", "i'm fine", "no need", "no thanks", "not needed"]
    location_queries = ["where are you", "your location", "where is TRU Buddy"]
    identity_queries = ["who are you", "what is your name", "introduce yourself"]
    basic_needs = ["hungry", "thirsty", "tired", "sleepy"]
    jokes = ["tell me a joke", "joke"]

    if any(greeting in message.lower() for greeting in greetings):
        return 'greeting'
    elif any(neg_response in message.lower() for neg_response in negative_responses):
        return 'negative_response'
    elif any(query in message.lower() for query in location_queries):
        return 'location_query'
    elif any(identity in message.lower() for identity in identity_queries):
        return 'identity_query'
    elif any(need in message.lower() for need in basic_needs):
        return 'basic_need'
    elif any(joke in message.lower() for joke in jokes):
        return 'joke'
    else:
        sentiment_score = sid.polarity_scores(message)
        if sentiment_score['compound'] <= -0.05:
            return 'negative_sentiment'
        elif sentiment_score['compound'] >= 0.05:
            return 'positive_sentiment'
        else:
            return 'neutral'

def generate_response(user_input):
    try:
        # Retrieve or create temporary conversation object
        if 'conversation' not in session:
            session['conversation'] = {'user_messages': [], 'bot_messages': []}
        
        # Create a new ChatSession instance for each request
        chat_session = genai.ChatSession(model)

        # Get the conversation history from the database
        conversation_history = get_conversation_history_from_db()

        # Construct the input message with the conversation history
        input_message = "\n".join([f"{m['role'].capitalize()}: {m['content']}" for m in conversation_history]) + f"\nUser: {user_input}"

        # Send the input message to the model
        response = chat_session.send_message(input_message)
        content = response.text
        
        # Store user message
        session['conversation']['user_messages'].append(user_input)
        # Store bot response
        session['conversation']['bot_messages'].append(content)
        
        # Store the message in the database
        store_message_in_db(user_input, 'user')
        store_message_in_db(content, 'bot')
        
        return {'fulfillmentText': content}
    except Exception as e:
        print(f"Error generating response from Gemini API: {e}")
        return {'error': 'Internal Server Error'}

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        user_input = data.get('message', '')
        gemini_response = generate_response(user_input)
        return jsonify(gemini_response)
    except Exception as e:
        print(f"Error handling chat message: {e}")
        return jsonify({'error': 'Internal Server Error'}), 500

@app.route('/delete_exercise', methods=['DELETE'])
def delete_exercise():
    exercise_id = request.args.get('id')
    try:
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        cursor.execute("DELETE FROM exercise WHERE id = %s", (exercise_id,))
        connection.commit()
        cursor.close()
        connection.close()
        return jsonify({'success': True})
    except mysql.connector.Error as e:
        print(f"Error deleting exercise: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        email = data.get('email')
        password = data.get('password')

        mydb = get_db_connection()
        if mydb:
            cursor = mydb.cursor()
            cursor.execute("SELECT * FROM users WHERE email = %s AND password = %s", (email, password))
            user = cursor.fetchone()

            cursor.close()
            mydb.close()

            if user:
                session['user_email'] = email
                session['user_name'] = user[3]

                token = secrets.token_hex(16)
                session['token'] = token

                response = jsonify({'message': 'Login successful', 'token': token, 'username': user[3]})
                response.set_cookie('token', token)
                return response
            else:
                return jsonify({'error': 'Invalid email or password'}), 401
        else:
            return jsonify({'error': 'Failed to connect to database'}), 500
    except Exception as e:
        print(f"Error handling login request: {e}")
        return jsonify({"error": "Internal Server Error"}), 500

@app.route('/signup', methods=['POST'])
def signup():
    try:
        data = request.get_json()
        full_name = data.get('fullname')
        email = data.get('email')
        password = data.get('password')
        mobile = data.get('mobile')

        mydb = get_db_connection()
        if mydb:
            cursor = mydb.cursor()
            cursor.execute("INSERT INTO users (email, password, full_name, mobile) VALUES (%s, %s, %s, %s)",
                           (email, password, full_name, mobile))
            mydb.commit()
            cursor.close()
            mydb.close()

            session['user_email'] = email
            session['user_name'] = full_name

            token = secrets.token_hex(16)
            session['token'] = token

            response = jsonify({'message': 'Signup successful', 'token': token, 'username': full_name})
            response.set_cookie('token', token)
            return response
        else:
            return jsonify({'error': 'Failed to connect to database'}), 500
    except Exception as e:
        print(f"Error handling signup request: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


def insert_exercise_data(exercise_title, exercise_name, exercise_description, video_link):
    try:
        connection = mysql.connector.connect(**db_config)
        cursor = connection.cursor()
        cursor.execute("INSERT INTO exercise (exercise_title, exercise_name, exercise_description, video_link) VALUES (%s, %s, %s, %s)",
                       (exercise_title, exercise_name, exercise_description, video_link))
        connection.commit()
        cursor.close()
        connection.close()
    except mysql.connector.Error as e:
        print(f"Error inserting exercise data: {e}")

@app.route('/save_exercise_data', methods=['POST'])
def save_exercise_data():
    try:
        data = request.get_json()
        exercise_title = data.get('exercise_title')
        exercise_name = data.get('exercise_name')
        exercise_description = data.get('exercise_description')
        video_link = data.get('video_link')

        insert_exercise_data(exercise_title, exercise_name, exercise_description, video_link)

        return jsonify({'message': 'Exercise data saved successfully'})
    except Exception as e:
        print(f"Error saving exercise data: {e}")
        return jsonify({'error': 'Internal Server Error'}), 500

@app.route('/get_module_exercises', methods=['GET'])
def get_module_exercises():
    module_title = request.args.get('module_title')
    connection = get_db_connection()
    if connection:
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM exercise WHERE exercise_title = %s", (module_title,))
        exercises = cursor.fetchall()
        cursor.close()
        connection.close()
        return jsonify(exercises)
    else:
        return jsonify({'error': 'Failed to connect to database'}), 500

@app.route('/exercise_details', methods=['POST'])
def exercise_details():
    data = request.get_json()
    return jsonify(data)

@app.route('/submit_assessment', methods=['POST'])
def submit_assessment():
    data = request.get_json()
    score = sum(int(data[f'question{i}']) for i in range(1, 9) if f'question{i}' in data)
    challenges = data.get('question9', '')
    comforts = data.get('question10', '')

    suggestion = generate_ai_suggestion(score, challenges, comforts)

    return jsonify({'suggestion': suggestion})

def generate_ai_suggestion(score, challenges, comforts):
    chat_session = genai.ChatSession(model2)
    input_text = f"Based on a score of {score} out of 32, with challenges in '{challenges}' and comfort measures being '{comforts}', what would be a good mental health advice?"
    response = chat_session.send_message(input_text)

    return response.text

if __name__ == "__main__":
    print("Starting Flask server...")
    app.run(debug=True)
