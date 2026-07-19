// 모바일 화면에서 메뉴 버튼과 실제 링크 목록을 찾는다
const toggle = document.querySelector("[data-nav-toggle]");
const links = document.querySelector("[data-nav-links]");

// 두 요소가 모두 존재할 때만 클릭 이벤트를 연결해 다른 화면의 오류를 막는다
if (toggle && links) {
  toggle.addEventListener("click", () => {
    // is-open 클래스를 켜거나 꺼서 CSS가 모바일 메뉴를 표시하거나 숨기게 한다
    links.classList.toggle("is-open");
  });
}
