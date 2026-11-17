// 견적 폼: 탭 이동, 탭별 오류 표시, 첨부 파일 목록, 업로드 진행률.
// 검증은 서버가 하고(htmx), 여기서는 화면 상태만 다룹니다.
document.addEventListener("alpine:init", () => {
  Alpine.data("inquiryForm", (initialStep, maxFiles, maxSize, allowedExt) => ({
    step: initialStep,
    files: [],
    fileError: "",
    dragging: false,
    progress: null,
    errSteps: [],

    init() {
      this.$nextTick(() => this.markErrors());
    },

    // 서버 검증 결과가 반영된 뒤, 오류 문구가 있는 탭을 표시
    markErrors() {
      this.errSteps = [...this.$root.querySelectorAll("section[data-step]")]
        .filter((sec) => [...sec.querySelectorAll(".field-err")].some((p) => p.textContent.trim()))
        .map((sec) => Number(sec.dataset.step));
    },

    go(n) {
      this.step = n;
      this.$nextTick(() => this.$root.scrollIntoView({ behavior: "smooth", block: "start" }));
    },

    // 서버 검증 실패: 오류가 있는 단계로 이동해 첫 오류 칸에 포커스
    invalid(n) {
      this.step = n;
      this.progress = null;
      if (window.turnstile) window.turnstile.reset();
      this.$nextTick(() => {
        this.markErrors();
        const err = [...this.$root.querySelectorAll(".field-err")].find(
          (p) => p.textContent.trim() && p.offsetParent !== null,
        );
        if (!err) return;
        const field = err.closest(".field, fieldset, div")?.querySelector("input, select, textarea");
        err.scrollIntoView({ behavior: "smooth", block: "center" });
        field?.focus({ preventScroll: true });
      });
    },

    // 입력 칸에서 Enter: 마지막 단계 전에는 제출 대신 "다음"
    onEnter(e) {
      if (e.target.tagName === "TEXTAREA" || e.target.tagName === "BUTTON") return;
      if (this.step < 3) {
        e.preventDefault();
        this.$refs["next" + this.step].click();
      }
    },

    onProgress(e) {
      if (e.detail.lengthComputable && this.files.length) {
        this.progress = Math.round((e.detail.loaded / e.detail.total) * 100);
      }
    },

    addFiles(list) {
      this.fileError = "";
      const problems = [];
      for (const f of list) {
        const ext = f.name.split(".").pop().toLowerCase();
        if (this.files.some((x) => x.name === f.name && x.size === f.size)) continue;
        if (!allowedExt.includes(ext)) problems.push(`${f.name}: 올릴 수 없는 형식`);
        else if (f.size > maxSize) problems.push(`${f.name}: 9MB 초과`);
        else if (f.size === 0) problems.push(`${f.name}: 빈 파일`);
        else if (this.files.length >= maxFiles) problems.push(`최대 ${maxFiles}개까지 첨부할 수 있습니다`);
        else this.files.push(f);
      }
      this.fileError = problems.join(", ");
      this.sync();
    },

    removeFile(i) {
      this.files.splice(i, 1);
      this.fileError = "";
      this.sync();
    },

    // 고른 파일을 실제 전송되는 <input type=file>에 반영
    sync() {
      const dt = new DataTransfer();
      this.files.forEach((f) => dt.items.add(f));
      this.$refs.files.files = dt.files;
    },

    size(bytes) {
      return bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)}MB` : `${Math.ceil(bytes / 1024)}KB`;
    },
  }));
});
