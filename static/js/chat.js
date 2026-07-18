const chatRoot = document.querySelector("[data-chat-root]");

if (chatRoot && typeof io !== "undefined") {
  const conversationId = chatRoot.dataset.conversationId;
  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
  const socket = io({ transports: ["websocket", "polling"] });
  const form = document.querySelector("[data-chat-form]");
  const input = document.querySelector("[data-chat-input]");
  const messages = document.querySelector("[data-chat-messages]");
  const errorBox = document.querySelector("[data-chat-error]");

  socket.on("connect", () => {
    socket.emit("join_conversation", {
      conversation_id: conversationId,
      csrf_token: csrfToken,
    });
  });

  socket.on("private_message", (data) => {
    if (data.conversation_id !== conversationId) return;
    const item = document.createElement("li");
    item.className = "message";
    const sender = document.createElement("strong");
    sender.textContent = data.sender;
    const content = document.createElement("p");
    content.textContent = data.message;
    item.append(sender, content);
    messages.appendChild(item);
    messages.scrollTop = messages.scrollHeight;
  });

  socket.on("chat_error", (data) => {
    errorBox.textContent = data.message || "메시지를 처리하지 못했습니다.";
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    socket.emit("send_private_message", {
      conversation_id: conversationId,
      csrf_token: csrfToken,
      message,
    });
    input.value = "";
  });
}
