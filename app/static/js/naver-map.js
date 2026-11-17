// 네이버 지도: [data-naver-map] 영역이 화면에 들어올 때만 SDK를 불러와 주소로 위치를 표시합니다.
// 키가 없으면 템플릿이 이 파일을 넣지 않고 '네이버 지도에서 보기' 링크만 보여 줍니다.
(() => {
  const els = document.querySelectorAll("[data-naver-map]");
  if (!els.length || !("IntersectionObserver" in window)) return;

  let sdk;
  const loadSdk = (clientId) =>
    (sdk ??= new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = `https://oapi.map.naver.com/openapi/v3/maps.js?ncpKeyId=${encodeURIComponent(clientId)}&submodules=geocoder`;
      s.onerror = reject;
      s.onload = () => {
        // geocoder 서브모듈은 본체 로드 후 추가로 불러와집니다.
        if (window.naver?.maps?.Service) resolve();
        else window.naver.maps.onJSContentLoaded = resolve;
      };
      document.head.appendChild(s);
    }));

  const render = (el) => {
    const { maps } = window.naver;
    maps.Service.geocode({ query: el.dataset.address }, (status, res) => {
      const addr = status === maps.Service.Status.OK && res.v2.addresses[0];
      if (!addr) return;
      const pos = new maps.LatLng(Number(addr.y), Number(addr.x));
      const map = new maps.Map(el, { center: pos, zoom: 16 });
      new maps.Marker({ position: pos, map, title: el.dataset.title });
    });
  };

  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      io.unobserve(e.target);
      loadSdk(e.target.dataset.clientId).then(() => render(e.target), () => {});
    }
  }, { rootMargin: "200px" });

  els.forEach((el) => io.observe(el));
})();
