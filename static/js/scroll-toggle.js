// 오른쪽 아래 버튼을 누르면 페이지 맨 아래로, 다시 누르면 맨 위로 이동한다
const scrollToggle = document.querySelector("[data-scroll-toggle]");

if (scrollToggle) {
  let goingDown = true;

  scrollToggle.addEventListener("click", () => {
    if (goingDown) {
      window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" });
      scrollToggle.classList.add("is-up");
      scrollToggle.setAttribute("aria-label", "페이지 맨 위로 이동");
    } else {
      window.scrollTo({ top: 0, behavior: "smooth" });
      scrollToggle.classList.remove("is-up");
      scrollToggle.setAttribute("aria-label", "페이지 맨 아래로 이동");
    }
    goingDown = !goingDown;
  });
}
