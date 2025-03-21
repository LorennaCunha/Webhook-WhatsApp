import os
import time
import requests 
import functions_framework

from flask import request, jsonify
from google.cloud import dialogflowcx_v3beta1 as dialogflow_cx

# Token de acesso do WhatsApp Business (1 hora)
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")

# Inicialização das credenciais do WhatsApp
WHATSAPP_VERIFICATION_TOKEN = os.getenv("WHATSAPP_VERIFICATION_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_API_URL = f"https://graph.facebook.com/v22.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"

# Inicialização das credenciais do Dialogflow
DIALOGFLOW_PROJECT = os.getenv("DIALOGFLOW_PROJECT")
DIALOGFLOW_AGENT_ID = os.getenv("DIALOGFLOW_AGENT_ID")
DIALOGFLOW_LOCATION = os.getenv("DIALOGFLOW_LOCATION")

# Firestore API
FIRESTORE_PROJECT_ID = os.getenv("FIRESTORE_PROJECT_ID")
FIRESTORE_API_URL = f"https://firestore.googleapis.com/v1/projects/{FIRESTORE_PROJECT_ID}/databases/(default)/documents/users"
FIRESTORE_ACCESS_TOKEN = os.getenv("FIRESTORE_ACCESS_TOKEN")

# Configuração do limitador de taxa
RATE_LIMIT = 10
BLOCK_TIME = 60 

@functions_framework.http
def whatsapp_webhook(request):
    """Processa mensagens recebidas do WhatsApp e responde via Dialogflow CX (SDK)"""

    user_ip = request.remote_addr  # Obtém o endereço IP do usuário
    current_time = int(time.time())

    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if token == WHATSAPP_VERIFICATION_TOKEN:
            return challenge, 200
        
        return "Token de verificação inválido", 403

    if request.method == "POST":
        req_data = request.get_json()

        if "entry" in req_data:
            for entry in req_data["entry"]:
                for change in entry["changes"]:
                    if "messages" in change["value"]:
                        for message in change["value"]["messages"]:
                            sender_id = message["from"]
                            user_message = message["text"]["body"]

                            # Verificar se o usuário já está cadastrado no Firestore via API REST
                            if not is_user_registered(sender_id):
                                register_user(sender_id)

                            if is_rate_limited(sender_id):
                                return jsonify({"error": "limite de requisições atingido"}), 429

                            response = send_to_dialogflow(sender_id, user_message)
                            send_whatsapp_message(sender_id, response)

        return jsonify({"status": "ok"}), 200


def is_user_registered(user_id):
    """Verifica se o usuário já está cadastrado no Firestore via API REST"""
    headers = {"Authorization": f"Bearer {FIRESTORE_ACCESS_TOKEN}"}
    response = requests.get(f"{FIRESTORE_API_URL}/{user_id}", headers=headers)
    return response.status_code == 200


def register_user(user_id):
    """Registra um novo usuário no Firestore via API REST"""
    headers = {
        "Authorization": f"Bearer {FIRESTORE_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "fields": {
            "phone": {"stringValue": user_id},
            "registered_at": {"timestampValue": time.strftime("%Y-%m-%dT%H:%M:%SZ")}
        }
    }
    requests.post(f"{FIRESTORE_API_URL}?documentId={user_id}", headers=headers, json=data)


def is_rate_limited(sender_id):
    """Verifica se o número de telefone do usuário excedeu o limite de chamadas"""
    return False  # Removido para focar na integração com Firestore REST API


def send_to_dialogflow(session_id, message):
    """Envia a mensagem do usuário para o Dialogflow CX usando o SDK oficial"""
    client_options = {"api_endpoint": f"{DIALOGFLOW_LOCATION}-dialogflow.googleapis.com"}
    client = dialogflow_cx.SessionsClient(client_options=client_options)
    
    session_path = client.session_path(
        project=DIALOGFLOW_PROJECT,
        location=DIALOGFLOW_LOCATION,
        agent=DIALOGFLOW_AGENT_ID,
        session=session_id
    )
    
    text_input = dialogflow_cx.TextInput(text=message)
    query_input = dialogflow_cx.QueryInput(text=text_input, language_code="pt-BR")
    request = dialogflow_cx.DetectIntentRequest(session=session_path, query_input=query_input)

    try:
        response = client.detect_intent(request=request)
    except Exception:
        return "Erro ao processar a resposta"

    messages = response.query_result.response_messages
    
    if messages:
        response_text = messages[0].text.text[0] if messages[0].text.text else "Não entendi sua mensagem."
        return response_text

    return "Erro ao processar a resposta"


def send_whatsapp_message(recipient, message):
    """Envia uma mensagem de resposta via WhatsApp API."""
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {"body": message}
    }
    
    requests.post(WHATSAPP_API_URL, headers=headers, json=data)
