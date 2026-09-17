const statusEl = document.getElementById('status');
const previewEl = document.getElementById('preview');

function render(items) {
  previewEl.textContent = JSON.stringify(items, null, 2);
}

chrome.storage.local.get({ products: [] }, ({ products }) => render(products));

async function getPageData() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.url || !/temu\.com/i.test(tab.url)) throw new Error('Temu өнім бетін ашыңыз.');
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => {
      const text = document.body.innerText || '';
      const title = document.title.replace(/\s*[-|].*$/, '').trim();
      const m = text.match(/(?:₸|KZT)\s*([0-9][0-9\s.,]*)|([0-9][0-9\s.,]*)\s*(?:₸|KZT)/i);
      const priceRaw = m ? (m[1] || m[2]) : null;
      const path = location.pathname;
      const id = (location.href.match(/(?:goods_id=|g-)(\d{8,18})/i) || [])[1] || '';
      const controls = [...document.querySelectorAll('button,[role="button"]')]
        .map(x => (x.innerText || '').trim())
        .filter(x => x && x.length <= 60);
      return { url: location.href, title, id, priceRaw, controls };
    }
  });
  return result;
}

function makeProduct(data) {
  const selected = data.controls.filter(x => !/[₸KZT$€£]/i.test(x)).slice(-8);
  const options = selected.slice(-4);
  const key = options.join(' / ') || 'default';
  return {
    id: data.id || data.url,
    url: data.url,
    title: data.title,
    variants: [{ key, options }]
  };
}

document.getElementById('save').addEventListener('click', async () => {
  try {
    const data = await getPageData();
    const product = makeProduct(data);
    chrome.storage.local.get({ products: [] }, ({ products }) => {
      const next = products.filter(p => p.id !== product.id);
      next.push(product);
      chrome.storage.local.set({ products: next }, () => {
        render(next);
        statusEl.textContent = 'Сақталды. Енді products.json файлын жүктеп, repo-ға салыңыз.';
      });
    });
  } catch (e) {
    statusEl.textContent = e.message;
  }
});

document.getElementById('download').addEventListener('click', () => {
  chrome.storage.local.get({ products: [] }, ({ products }) => {
    const blob = new Blob([JSON.stringify(products, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    chrome.downloads.download({ url, filename: 'products.json', saveAs: true });
  });
});
