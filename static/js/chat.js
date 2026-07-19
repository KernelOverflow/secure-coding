// 현재 페이지가 채팅 상세 화면인지 확인할 기준 요소를 찾는다
const chatRoot = document.querySelector("[data-chat-root]");

// 채팅 화면이고 Socket.IO 라이브러리도 정상 로드된 경우에만 실시간 기능을 시작한다
if (chatRoot && typeof io !== "undefined") {
  // HTML의 data 속성과 CSRF 메타 태그에서 서버로 보낼 안전한 값을 가져온다
  const conversationId = chatRoot.dataset.conversationId;
  const currentUserId = chatRoot.dataset.currentUserId;
  const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
  // 웹소켓을 우선 사용하고 지원되지 않을 때는 polling 방식으로 연결한다
  const socket = io({ transports: ["websocket", "polling"] });

  // 메시지 입력, 목록, 오류 영역을 한 번 찾아 이후 이벤트에서 재사용한다
  const form = document.querySelector("[data-chat-form]");
  const input = document.querySelector("[data-chat-input]");
  const messages = document.querySelector("[data-chat-messages]");
  const errorBox = document.querySelector("[data-chat-error]");

  socket.on("connect", () => {
    // 연결 직후 현재 대화방 UUID와 CSRF 토큰을 보내 참가 권한을 서버에서 확인받는다
    socket.emit("join_conversation", {
      conversation_id: conversationId,
      csrf_token: csrfToken,
    });
  });

  socket.on("private_message", (data) => {
    // 혹시 다른 대화방 데이터가 도착해도 현재 화면의 메시지만 표시한다
    if (data.conversation_id !== conversationId) return;
    // 사용자 메시지는 HTML 문자열로 넣지 않고 textContent로 넣어 스크립트 실행을 막는다
    const item = document.createElement("li");
    item.className = "message";
    item.classList.add(String(data.sender_id) === currentUserId ? "message-own" : "message-other");

    let avatar;
    if (data.sender_avatar_url) {
      avatar = document.createElement("img");
      avatar.className = "profile-avatar message-avatar";
      avatar.src = data.sender_avatar_url;
      avatar.alt = `${data.sender} 프로필 사진`;
    } else {
      avatar = document.createElement("div");
      avatar.className = "profile-avatar message-avatar profile-avatar-placeholder";
      avatar.setAttribute("aria-hidden", "true");
      avatar.textContent = data.sender.slice(0, 1);
    }

    const body = document.createElement("div");
    body.className = "message-body";
    const sender = document.createElement("strong");
    sender.textContent = data.sender;
    const content = document.createElement("p");
    content.textContent = data.message;
    body.append(sender, content);

    item.append(avatar, body);
    messages.appendChild(item);
    // 새 메시지가 추가되면 사용자가 바로 볼 수 있도록 목록 맨 아래로 이동한다
    messages.scrollTop = messages.scrollHeight;
  });

  socket.on("chat_error", (data) => {
    // 권한, 형식, 전송 속도 오류를 채팅 입력창 아래에 안전한 텍스트로 표시한다
    errorBox.textContent = data.message || "메시지를 처리하지 못했습니다.";
  });

  form.addEventListener("submit", (event) => {
    // 일반 폼 제출로 페이지가 새로고침되지 않게 하고 Socket 이벤트로 전송한다
    event.preventDefault();
    const message = input.value.trim();
    // 공백뿐인 메시지는 서버에 보내지 않는다
    if (!message) return;
    socket.emit("send_private_message", {
      conversation_id: conversationId,
      csrf_token: csrfToken,
      message,
    });
    // 전송 요청을 보낸 뒤 다음 메시지를 작성할 수 있도록 입력창을 비운다
    input.value = "";
  });
}
