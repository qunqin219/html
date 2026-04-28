document.addEventListener('DOMContentLoaded', async () => {
    const modelListContainer = document.getElementById('model-list');
    if (!modelListContainer) return;

    try {
        const response = await fetch('data/models.json');
        const data = await response.json();
        const models = data.models;

        modelListContainer.innerHTML = models.map(model => `
            <a href="models/model.html?id=${model.id}" class="model-card-link">
                <div class="model-item">
                    <span class="rank">${String(model.rank).padStart(2, '0')}</span>
                    <div class="model-info">
                        <div class="model-header">
                            <span class="model-name">${model.name}</span>
                            <span class="model-company">${model.company}</span>
                            ${model.badge ? `<span class="badge badge-${model.badgeType}">${model.badge}</span>` : ''}
                        </div>
                        <p class="model-desc">${model.description}</p>
                        <div class="model-tags">
                            ${model.tags.map(tag => `<span class="tag">${tag}</span>`).join('')}
                        </div>
                    </div>
                    <div class="model-action">
                        <span class="price">${model.price}</span>
                        <span class="link">查看详情 →</span>
                    </div>
                </div>
            </a>
        `).join('');

        const metaCount = document.querySelector('.meta-value');
        if (metaCount) {
            metaCount.textContent = `${models.length} 个模型`;
        }

        if (window.location.hash === '#model-list') {
            setTimeout(() => {
                modelListContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }, 300);
        }

    } catch (error) {
        console.error('Failed to load models:', error);
        modelListContainer.innerHTML = '<p style="padding: 2rem;">加载数据失败，请刷新页面重试。</p>';
    }
});
