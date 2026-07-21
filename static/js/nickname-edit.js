// 닉네임 옆 연필 버튼을 누르면 제목을 같은 자리의 입력창으로 바꾸고 저장·취소 버튼을 보여준다
const nicknameForm = document.querySelector("[data-nickname-form]");

if (nicknameForm) {
  const display = nicknameForm.querySelector("[data-nickname-display]");
  const input = nicknameForm.querySelector("[data-nickname-input]");
  const editButton = nicknameForm.querySelector("[data-nickname-edit]");
  const actions = nicknameForm.querySelector("[data-nickname-actions]");
  const cancelButton = nicknameForm.querySelector("[data-nickname-cancel]");
  const originalNickname = input.value;

  const enterEditMode = () => {
    display.hidden = true;
    editButton.hidden = true;
    input.hidden = false;
    actions.hidden = false;
    input.focus();
    input.select();
  };

  const exitEditMode = () => {
    input.value = originalNickname;
    input.hidden = true;
    actions.hidden = true;
    display.hidden = false;
    editButton.hidden = false;
  };

  editButton.addEventListener("click", enterEditMode);
  cancelButton.addEventListener("click", exitEditMode);
}
