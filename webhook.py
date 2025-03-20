import os
import time
import requests 
import functions_framework

from flask import request, jsonify
from google.cloud import firestore
from google.cloud import dialogflowcx_v3beta1 as dialogflow_cx

# Token de acesso do WhatsApp Business (1 hora)
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")

#Inicialização das credenciais do WhatsApp
WHATSAPP_VERIFICATION_TOKEN = os.getenv("WHATSAPP_VERIFICATION_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_API_URL = f"https://graph.facebook.com/v22.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"

# Inicialização do cliente Firestore
db = firestore.Client()

#Inicialização das credenciais do Dialogflow
DIALOGFLOW_PROJECT = os.getenv("DIALOGFLOW_PROJECT")
DIALOGFLOW_AGENT_ID = os.getenv("DIALOGFLOW_AGENT_ID")
DIALOGFLOW_LOCATION = os.getenv("DIALOGFLOW_LOCATION")

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

                            if is_rate_limited(sender_id):
                                return jsonify({"error": "limite de requisições atingido"}), 429

                            response = send_to_dialogflow(sender_id, user_message)
                            send_whatsapp_message(sender_id, response)

        return jsonify({"status": "ok"}), 200


def is_rate_limited(sender_id):
    """Verifica se o número de telefone do usuário excedeu o limite de chamadas"""

    user_reference = db.collection("rate_limit").document(sender_id)
    current_time = int(time.time())
    
    user_data = user_reference.get()

    if user_data.exists:
        data = user_data.to_dict()
        last_request_time = data["last_request_time"]
        request_count = data["request_count"]

        if current_time - last_request_time < BLOCK_TIME:
            if request_count >= RATE_LIMIT:
                return True

        if current_time - last_request_time >= BLOCK_TIME:
            request_count = 0

        request_count += 1
        user_reference.update({
            "last_request_time": current_time,
            "request_count": request_count
        })
    else:
        user_reference.set({
            "last_request_time": current_time,
            "request_count": 1,
            "blocks": 0
        })
    
    return False 


def send_to_dialogflow(session_id, message):
    """Envia a mensagem do usuário para o Dialogflow CX usando o SDK oficial"""

    client_options = {"api_endpoint": f"{location}-dialogflow.googleapis.com"}
    client = dialogflow_cx.SessionsClient(client_options=client_options)

    session_path = client.session_path(
        project=project_id,
        location=location,
        agent=agent_id,
        session=session_id
    )

    text_input = dialogflow_cx.TextInput(text=message)
    query_input = dialogflow_cx.QueryInput(text=text_input, language_code="pt-BR")

    request = dialogflow_cx.DetectIntentRequest(session=session_path, query_input=query_input)

    try:
        response = client.detect_intent(request=request)
    except Exception as e:
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
        "text": {
            "body": message
        }
    }

    response = requests.post(WHATSAPP_API_URL, headers=headers, json=data)

    return response.status_code
