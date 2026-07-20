// 삭제 확인 속성이 붙은 폼을 하나의 공통 모달로 처리한다
const confirmDialog = document.querySelector("[data-confirm-dialog]");

if (confirmDialog) {
  const message = confirmDialog.querySelector("[data-confirm-dialog-message]");
  const cancelButton = confirmDialog.querySelector("[data-confirm-cancel]");
  const acceptButton = confirmDialog.querySelector("[data-confirm-accept]");
  let pendingForm = null;
  let pendingSubmitter = null;

  // 관리자 선택 폼은 실제 삭제 값을 선택했을 때만 확인한다
  const needsConfirmation = (form) => {
    const selectName = form.dataset.confirmSelect;
    if (!selectName) return true;
    const select = form.elements.namedItem(selectName);
    return select && select.value === form.dataset.confirmValue;
  };

  document.addEventListener("submit", (event) => {
    const form = event.target.closest("form[data-confirm-message]");
    if (!form || !needsConfirmation(form)) return;

    // 모달에서 확인한 뒤 재제출한 폼은 한 번만 그대로 통과시킨다
    if (form.dataset.confirmed === "true") {
      delete form.dataset.confirmed;
      return;
    }

    event.preventDefault();
    pendingForm = form;
    pendingSubmitter = event.submitter;
    message.textContent = form.dataset.confirmMessage;
    confirmDialog.showModal();
  });

  // 취소하거나 Esc로 닫으면 보관한 제출 정보를 모두 버린다
  const clearPendingSubmission = () => {
    pendingForm = null;
    pendingSubmitter = null;
  };

  cancelButton.addEventListener("click", () => {
    confirmDialog.close();
    clearPendingSubmission();
  });

  confirmDialog.addEventListener("cancel", clearPendingSubmission);

  acceptButton.addEventListener("click", () => {
    if (!pendingForm) return;
    const form = pendingForm;
    const submitter = pendingSubmitter;
    clearPendingSubmission();
    confirmDialog.close();
    form.dataset.confirmed = "true";
    if (submitter && submitter.isConnected) form.requestSubmit(submitter);
    else form.requestSubmit();
  });
}
