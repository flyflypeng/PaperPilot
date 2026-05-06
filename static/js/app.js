// Global state
let categories = {};
let hasLoadedCategories = false; // Whether the category has been loaded
let hasLoadedPapersDir = false; // Whether the papers directory path has been loaded

let currentCategoryId = null;
let currentPaperId = null;
let papers = [];
let expandedCategories = new Set(); // expanded category ids
let draggedPaper = null; // currently dragged paper
let draggedCategory = null; // currently dragged single category
let draggedCategories = []; // currently dragged multiple categories
let dragExpandTimer = null; // timer for auto-expanding on drag
let currentViewMode = 'category'; // 'category' | 'translating' | 'analyzing' | 'reading-list'
let readingListCount = 0; // reading list size
let readingListPaperIds = new Set(); // ids in reading list

// Helper: Run callback when DOM is ready (or immediately if already ready)
function onAppReady(callback) {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', callback);
    } else {
        callback();
    }
}

// Translation-related
let translationQueue = []; // translation queue
let isTranslating = false; // whether translating now
let translationStatus = {}; // {paperId: 'translating' | 'queued' | 'completed' | 'error', queuePosition, taskId}
let translationLogInterval = {}; // polling intervals per task

// AI analysis-related
let analysisQueue = []; // analysis queue
let isAnalyzing = false; // whether analyzing now
let analysisStatus = {}; // {paperId: 'analyzing' | 'queued' | 'completed' | 'error', queuePosition, taskId, step}
let analysisLogInterval = {}; // polling intervals per task

// Persist queues to localStorage
function saveQueuesToStorage() {
    try {
        localStorage.setItem('translationQueue', JSON.stringify(translationQueue));
        localStorage.setItem('analysisQueue', JSON.stringify(analysisQueue));
        localStorage.setItem('translationStatus', JSON.stringify(translationStatus));
        localStorage.setItem('analysisStatus', JSON.stringify(analysisStatus));
    } catch (e) {
        console.error('Failed to save queue state:', e);
    }
}

// Restore queues from localStorage
function restoreQueuesFromStorage() {
    try {
        const savedTQueue = localStorage.getItem('translationQueue');
        const savedAQueue = localStorage.getItem('analysisQueue');
        const savedTStatus = localStorage.getItem('translationStatus');
        const savedAStatus = localStorage.getItem('analysisStatus');

        if (savedTQueue) {
            translationQueue = JSON.parse(savedTQueue);
        }
        if (savedAQueue) {
            analysisQueue = JSON.parse(savedAQueue);
        }
        if (savedTStatus) {
            translationStatus = JSON.parse(savedTStatus);
        }
        if (savedAStatus) {
            analysisStatus = JSON.parse(savedAStatus);
        }
    } catch (e) {
        console.error('Failed to restore queue state:', e);
        translationQueue = [];
        analysisQueue = [];
        translationStatus = {};
        analysisStatus = {};
    }
}

// Clean completed/failed items from queues
function cleanupCompletedQueues() {
    translationQueue = translationQueue.filter(pid => {
        const status = translationStatus[pid];
        return status && (status.status === 'queued' || status.status === 'translating');
    });

    analysisQueue = analysisQueue.filter(pid => {
        const status = analysisStatus[pid];
        return status && (status.status === 'queued' || status.status === 'analyzing');
    });

    Object.keys(translationStatus).forEach(pid => {
        const status = translationStatus[pid];
        if (status.status === 'completed' || status.status === 'error') {
            delete translationStatus[pid];
        }
    });

    Object.keys(analysisStatus).forEach(pid => {
        const status = analysisStatus[pid];
        if (status.status === 'completed' || status.status === 'error') {
            delete analysisStatus[pid];
        }
    });

    saveQueuesToStorage();
}

// Paper multi-select
let isMultiSelectMode = false;
let selectedPaperIds = new Set();
let lastSelectedIndex = null; // for shift-select

// Category multi-select
let isCategoryMultiSelectMode = false;
let selectedCategoryIds = new Set();
let lastSelectedCategoryIndex = null; // for shift-select categories

// DOM elements
const categoryTree = document.getElementById('category-tree');
const papersList = document.getElementById('papers-list');
const paperInfo = document.getElementById('paper-info');
const currentCategoryTitle = document.getElementById('current-category');
const modal = document.getElementById('modal');
const contextMenu = document.getElementById('context-menu');
const paperContextMenu = document.getElementById('paper-context-menu');
const uploadZone = document.getElementById('upload-zone');
const fileInput = document.getElementById('file-input');
const loading = document.getElementById('loading');

function showInfoPanel() {
    const panel = document.getElementById('info-panel');
    if (!panel) return;
    panel.style.display = 'flex';
    const btn = document.getElementById('toggle-right-sidebar');
    if (btn) btn.classList.add('active');
}

function hideInfoPanel() {
    const panel = document.getElementById('info-panel');
    if (!panel) return;
    panel.classList.remove('wide');
    panel.style.display = 'none';
    const btn = document.getElementById('toggle-right-sidebar');
    if (btn) btn.classList.remove('active');
}

// Save current view state
function saveCurrentViewState() {
    const settingView = document.getElementById('setting-view');
    const isSettingView = settingView && settingView.style.display !== 'none';

    const dailyArxivView = document.getElementById('daily-arxiv-view');
    const isDailyArxivView = dailyArxivView && dailyArxivView.style.display !== 'none';

    let settingPanel = null;
    if (isSettingView) {
        const activeNav = document.querySelector('.setting-nav-item.active');
        settingPanel = activeNav?.dataset.setting || 'overview';
    }

    let tabName = 'paper';
    if (isSettingView) tabName = 'setting';
    else if (isDailyArxivView) tabName = 'daily-arxiv';

    const state = {
        viewMode: currentViewMode,
        categoryId: currentCategoryId,
        tabName: tabName,
        settingPanel: settingPanel,
        dailyArxivCategory: dailyArxivCurrentCategory,
        dailyArxivDate: dailyArxivCurrentDate,
        // keep Daily arXiv filter status
        dailyArxivFilters: {
            selectedAffiliations: Array.from(dailyArxivSelectedAffiliations),
            selectedCountries: Array.from(dailyArxivSelectedCountries),
            selectedKeywords: Array.from(dailyArxivSelectedKeywords),
            excludedAffiliations: Array.from(dailyArxivExcludedAffiliations),
            excludedCountries: Array.from(dailyArxivExcludedCountries),
            excludedKeywords: Array.from(dailyArxivExcludedKeywords),
            filterFirstAffiliation: dailyArxivFilterFirstAffiliation,
            hideUnknownFirstAffiliation: dailyArxivHideUnknownFirstAffiliation,
            searchQuery: dailyArxivSearchQuery
        }
    };
    try {
        sessionStorage.setItem('currentViewState', JSON.stringify(state));
    } catch (e) {
        console.error('Failed to save current view state:', e);
    }
}

// Restore last view state
async function restoreViewState(preloadedReadingListPapers = null) {
    try {
        const saved = sessionStorage.getItem('currentViewState');
        if (saved) {
            const state = JSON.parse(saved);

            if (state.tabName === 'setting') {
                switchTab('setting');
                if (state.settingPanel) {
                    switchSettingPanel(state.settingPanel);
                }
                return;
            }

            // Restore Daily arXiv view
            if (state.tabName === 'daily-arxiv') {
                // Restore selected category and date
                if (state.dailyArxivCategory) {
                    dailyArxivCurrentCategory = state.dailyArxivCategory;
                }
                if (state.dailyArxivDate) {
                    dailyArxivCurrentDate = state.dailyArxivDate;
                }
                // Restore filters
                if (state.dailyArxivFilters) {
                    const filters = state.dailyArxivFilters;
                    if (filters.selectedAffiliations) {
                        dailyArxivSelectedAffiliations = new Set(filters.selectedAffiliations);
                    }
                    if (filters.selectedCountries) {
                        dailyArxivSelectedCountries = new Set(filters.selectedCountries);
                    }
                    if (filters.selectedKeywords) {
                        dailyArxivSelectedKeywords = new Set(filters.selectedKeywords);
                    }
                    if (filters.excludedAffiliations) {
                        dailyArxivExcludedAffiliations = new Set(filters.excludedAffiliations);
                    }
                    if (filters.excludedCountries) {
                        dailyArxivExcludedCountries = new Set(filters.excludedCountries);
                    }
                    if (filters.excludedKeywords) {
                        dailyArxivExcludedKeywords = new Set(filters.excludedKeywords);
                    }
                    if (typeof filters.filterFirstAffiliation === 'boolean') {
                        dailyArxivFilterFirstAffiliation = filters.filterFirstAffiliation;
                    }
                    if (typeof filters.hideUnknownFirstAffiliation === 'boolean') {
                        dailyArxivHideUnknownFirstAffiliation = filters.hideUnknownFirstAffiliation;
                    }
                    if (filters.searchQuery) {
                        dailyArxivSearchQuery = filters.searchQuery;
                        // Restore search input value
                        const searchInput = document.getElementById('daily-arxiv-search');
                        if (searchInput) {
                            searchInput.value = filters.searchQuery;
                        }
                    }
                }
                switchTab('daily-arxiv');
                return;
            }

            switchTab('paper');
            if (state.viewMode === 'reading-list' || state.viewMode === 'translating' || state.viewMode === 'analyzing') {
                await showReadingList(preloadedReadingListPapers);
                return;
            }
            if (state.viewMode === 'category' && state.categoryId) {
                // First expand the path to the target category
                expandToCategoryPath(state.categoryId);
                // Select target category
                const categoryItem = document.querySelector(`.category-item[data-category-id="${state.categoryId}"]`);
                if (categoryItem) {
                    // Manually set selected status
                    document.querySelectorAll('.category-item.selected').forEach(item => item.classList.remove('selected'));
                    categoryItem.classList.add('selected');
                }
                // Directly load papers in this category（make sure await）
                await loadPapers(state.categoryId);
                return;
            }

            await renderRecentIfNoCategory();
            return;
        }

        switchTab('paper');
        await renderRecentIfNoCategory();
    } catch (e) {
        console.error('Failed to restore view state:', e);
        switchTab('paper');
        await renderRecentIfNoCategory();
    }
}

// Expand all ancestors for a target category
function expandToCategoryPath(targetCategoryId) {
    // DFS to find path from root to target
    function findCategoryPath(node, targetId, path = []) {
        if (node.id === targetId) {
            return path;
        }
        if (node.children) {
            for (const child of node.children) {
                const result = findCategoryPath(child, targetId, [...path, node.id]);
                if (result) return result;
            }
        }
        return null;
    }

    const path = findCategoryPath(categories, targetCategoryId, []);
    if (path) {
        // Expand all categories along the path
        path.forEach(categoryId => {
            if (categoryId === 'root') return;
            const categoryElement = document.querySelector(`[data-category-id="${categoryId}"]`);
            if (categoryElement) {
                const container = categoryElement.closest('.category-container');
                const toggle = container?.querySelector('.category-toggle');
                const children = container?.querySelector('.category-children');

                if (toggle && children) {
                    toggle.classList.add('expanded');
                    children.classList.remove('collapsed');
                    expandedCategories.add(categoryId);
                }
            }
        });
    }
}

async function bootstrapApp() {
    if (window.__PAPERPILOT_APP_BOOTSTRAPPED) {
        return;
    }
    window.__PAPERPILOT_APP_BOOTSTRAPPED = true;

    try {
        // Determine whether you need to load a directory tree (sidebar visible or restore category view)
        const leftSidebar = document.querySelector('.sidebar');
        let shouldLoadCategories = leftSidebar && leftSidebar.style.display !== 'none';

        if (!shouldLoadCategories) {
            try {
                const savedState = sessionStorage.getItem('currentViewState');
                if (savedState) {
                    const state = JSON.parse(savedState);
                    if (state.viewMode === 'category' && state.categoryId) {
                        shouldLoadCategories = true;
                    }
                }
            } catch (e) { }
        }

        if (shouldLoadCategories) {
            await loadCategories();
        }

        setupEventListeners();
        setupNavigation();
        loadAgenticSettings().catch(err => {
            console.error('Error loading agentic settings:', err);
        });
        await initImportFeature();
        await initDailyArxiv();
        updateAvatars();
    } catch (e) {
        console.error('Error during app initialization:', e);
    }
    const readingListPapers = await updateReadingListCount();
    restoreQueuesFromStorage();
    cleanupCompletedQueues();
    await restoreActiveTasks();
    if (translationQueue.length > 0 && !isTranslating) {
        processTranslationQueue();
    }
    if (analysisQueue.length > 0 && !isAnalyzing) {
        processAnalysisQueue();
    }
    await restoreViewState(readingListPapers);
    updateTaskIndicator();
}

onAppReady(bootstrapApp);

// Wire up DOM event listeners
function setupEventListeners() {
    // Add-category button: create child under selected or root otherwise
    document.getElementById('add-root-category').addEventListener('click', () => {
        if (currentCategoryId && currentCategoryId !== 'root') {
            // Selected category: add subcategory under it
            startInlineAddCategory(currentCategoryId);
        } else {
            // No selection: add root category
            startInlineAddCategory('root');
        }
    });

    // Upload PDF button
    document.getElementById('upload-btn').addEventListener('click', () => {
        // Allow upload in reading-list view as well
        if (currentCategoryId || currentViewMode === 'reading-list') {
            fileInput.click();
        } else {
            showMessage('Please select a category first', 'warning');
        }
    });

    // Import from arXiv button
    document.getElementById('upload-arxiv-btn').addEventListener('click', () => {
        // Allow import in reading-list view as well
        if (currentCategoryId || currentViewMode === 'reading-list') {
            showArxivUploadModal();
        } else {
            showMessage('Please select a category first', 'warning');
        }
    });

    // Refresh button
    document.getElementById('refresh-papers').addEventListener('click', () => {
        if (currentCategoryId) {
            loadPapers(currentCategoryId);
        }
    });

    // Toggle multi-select button
    document.getElementById('toggle-multiselect').addEventListener('click', (e) => {
        e.stopPropagation();
        toggleMultiSelectMode();
    });

    // File input
    fileInput.addEventListener('change', handleFileSelect);

    // Sort selector
    document.getElementById('sort-by').addEventListener('change', () => {
        if (papers.length > 0) {
            renderPapersList();
        }
    });

    // Batch toolbar actions
    const batchAnalyze = document.getElementById('batch-analyze');
    const batchTranslate = document.getElementById('batch-translate');
    const batchDelete = document.getElementById('batch-delete');
    const batchCancel = document.getElementById('batch-cancel');
    if (batchAnalyze) batchAnalyze.addEventListener('click', onBatchAnalyze);
    if (batchTranslate) batchTranslate.addEventListener('click', onBatchTranslate);
    if (batchDelete) batchDelete.addEventListener('click', onBatchDelete);
    if (batchCancel) batchCancel.addEventListener('click', (e) => { e.stopPropagation(); exitMultiSelectMode(); });

    // Logo Click to return to the main interface
    const navbarBrand = document.getElementById('navbar-brand');
    const navbarLogo = document.getElementById('navbar-logo');
    const navbarBrandText = document.getElementById('navbar-brand-text');
    if (navbarBrand) {
        navbarBrand.addEventListener('click', returnToHome);
    }
    if (navbarLogo) {
        navbarLogo.addEventListener('click', returnToHome);
    }
    if (navbarBrandText) {
        navbarBrandText.addEventListener('click', returnToHome);
    }

    // global search
    setupGlobalSearch();

    // Drag and drop upload
    setupDragAndDrop();

    // modal box
    setupModal();

    // right click menu
    setupContextMenu();
    setupPaperContextMenu();

    // Panel adjustment
    setupSidebarResizing();
    setupInfoPanelResizing();

    // Click on an empty space to close the menu
    document.addEventListener('click', (e) => {
        contextMenu.style.display = 'none';
        paperContextMenu.style.display = 'none';
        // In the multi-select mode of papers, click on the blank area of ​​the main area to exit.
        if (isMultiSelectMode) {
            const main = document.querySelector('.main-content');
            const isInsideMain = main && main.contains(e.target);
            const isPaperItem = e.target.closest && e.target.closest('.paper-item');
            const isToolbar = e.target.closest && e.target.closest('#batch-toolbar');
            const isToggleBtn = e.target.closest && e.target.closest('#toggle-multiselect');
            if (isInsideMain && !isPaperItem && !isToolbar && !isToggleBtn) {
                exitMultiSelectMode();
            }
        }
        // In the directory multi-select state, click the non-directory item area to exit.
        if (isCategoryMultiSelectMode) {
            const isCategoryItem = e.target.closest && e.target.closest('.category-item');
            const isCategoryBatchMenu = e.target.closest && e.target.closest('.category-batch-menu');
            // If the click is not a directory item or a batch operation menu, exit the multi-select
            if (!isCategoryItem && !isCategoryBatchMenu) {
                exitCategoryMultiSelectMode();
            }
        }
    });

    // Click on a blank area of ​​the classification tree
    categoryTree.addEventListener('click', (e) => {
        if (e.target === categoryTree) {
            // If there are multiple selection directories, do not clear them and maintain the multi-selection status.
            if (!isCategoryMultiSelectMode) {
                document.querySelectorAll('.category-item.selected').forEach(item => item.classList.remove('selected'));
                currentCategoryId = null;
                // Only switch to the to-read list if you are not currently in the to-read list
                if (currentViewMode !== 'reading-list') {
                    showReadingList();
                    clearPaperInfo();
                }
            }
        }
    });

    // Right-click menu of blank area of ​​classification tree（Supports batch operations of multiple-select directories）
    categoryTree.addEventListener('contextmenu', (e) => {
        // If you click on a blank area of ​​the classification tree and there are multiple selected directories, the batch menu will be displayed.
        if (e.target === categoryTree && isCategoryMultiSelectMode && selectedCategoryIds.size > 0) {
            e.preventDefault();
            showCategoryBatchContextMenu(e);
        }
    });
}

// Load category data
async function loadCategories(silent = false) {
    try {
        if (!silent) {
            showLoading(true);
        }
        const response = await fetch('/api/categories');
        categories = await response.json();
        renderCategoryTree();
    } catch (error) {
        console.error('Failed to load categories:', error);
        showMessage('Failed to load categories', 'error');
    } finally {
        if (!silent) {
            showLoading(false);
        }
    }
}

// Render category tree
function renderCategoryTree() {
    categoryTree.innerHTML = '';
    if (categories.children) {
        // Top-level category sorting: top > Others > by name
        const sorted = [...categories.children].sort((a, b) => {
            // Top directory priority
            if (a.pinned && !b.pinned) return -1;
            if (!a.pinned && b.pinned) return 1;
            // Then Others Table of contents
            if (a.name === 'Others') return -1;
            if (b.name === 'Others') return 1;
            // Last sorted by name
            return (a.name || '').localeCompare(b.name || '');
        });
        sorted.forEach(category => {
            const element = createCategoryElement(category);
            categoryTree.appendChild(element);
        });
    }
}

// Refresh category data (without rerender)
async function updateCategoriesData() {
    try {
        const response = await fetch('/api/categories');
        categories = await response.json();
        hasLoadedCategories = true;
    } catch (error) {
        console.error('Failed to refresh category data:', error);
    }
}

// State-preserving rendering classification tree
async function renderCategoryTreeWithState() {
    // Save current expanded state
    saveExpandedState();

    // Re-render
    renderCategoryTree();

    // Restore expanded state
    restoreExpandedState();

    // Restore selected state
    if (currentCategoryId) {
        const categoryElement = document.querySelector(`[data-category-id="${currentCategoryId}"]`);
        if (categoryElement) {
            categoryElement.classList.add('selected');
        }
    }
}

// Save expanded state
function saveExpandedState() {
    expandedCategories.clear();
    document.querySelectorAll('.category-toggle.expanded').forEach(toggle => {
        const categoryItem = toggle.closest('.category-container').querySelector('.category-item');
        if (categoryItem) {
            expandedCategories.add(categoryItem.dataset.categoryId);
        }
    });
}

// Restore expanded state
function restoreExpandedState() {
    expandedCategories.forEach(categoryId => {
        const categoryElement = document.querySelector(`[data-category-id="${categoryId}"]`);
        if (categoryElement) {
            const container = categoryElement.closest('.category-container');
            const toggle = container.querySelector('.category-toggle');
            const children = container.querySelector('.category-children');

            if (toggle && children) {
                toggle.classList.add('expanded');
                children.classList.remove('collapsed');
            }
        }
    });
}

// Create taxonomy elements
function createCategoryElement(category, level = 0) {
    // Create main container
    const container = document.createElement('div');
    container.className = 'category-container';

    // Create classification items
    const div = document.createElement('div');
    div.className = 'category-item';
    if (category.pinned) {
        div.classList.add('pinned');
    }
    div.dataset.categoryId = category.id;
    div.dataset.level = level; // storage hierarchy
    div.style.paddingLeft = `${level * 20 + 12}px`;
    div.tabIndex = 0; // Make elements focusable and support keyboard events

    const hasChildren = category.children && category.children.length > 0;

    // Get icon color: custom color > Othersgrey > Default purple
    const isOthers = category.name === 'Others';
    const folderColor = category.iconColor || (isOthers ? '#8b949e' : '#7d4a9d');

    // Pin icon
    const pinIcon = category.pinned ? '<i class="fas fa-thumbtack pin-icon"></i>' : '';

    div.innerHTML = `
        ${hasChildren ? '<button class="category-toggle"><i class="fas fa-chevron-right"></i></button>' : '<span class="category-toggle-placeholder"></span>'}
        <i class="fas fa-folder" style="margin-right: 6px; color: ${folderColor}; font-size: 12px;"></i>
        <span class="category-name">${category.name}</span>${pinIcon}
        <span class="pdf-count">${category.pdf_count || 0}</span>
    `;

    // click event - Support multiple selection
    div.addEventListener('click', (e) => {
        e.stopPropagation();

        // Ctrl/Cmd + Click: switch multiple selections
        if (e.ctrlKey || e.metaKey) {
            handleCategoryMultiSelectClick(e, category.id, div);
            return;
        }

        // Shift + Click: Range selection
        if (e.shiftKey && lastSelectedCategoryIndex !== null) {
            handleCategoryShiftSelect(category.id, div);
            return;
        }

        // Normal click - Clear multiple selection status
        if (isCategoryMultiSelectMode) {
            exitCategoryMultiSelectMode();
        }

        // No matter where you click on a category item, its subcategories will be expanded first.（if exists）
        const children = container.querySelector('.category-children');
        const toggle = div.querySelector('.category-toggle');
        if (children && children.classList.contains('collapsed')) {
            children.classList.remove('collapsed');
            if (toggle) toggle.classList.add('expanded');
            expandedCategories.add(category.id);
        }

        // If you click on the selected category repeatedly, it will be deselected and the to-be-read list will be displayed.
        if (div.classList.contains('selected')) {
            div.classList.remove('selected');
            currentCategoryId = null;
            // Show to-read list
            showReadingList();
            clearPaperInfo();
            return;
        }

        // Record selection index
        lastSelectedCategoryIndex = getCategoryIndex(category.id);
        // Select a category and load the paper（Regardless of whether there are subdirectories, the papers in this directory must be displayed.）
        // Ensures that papers in the current directory are loaded and displayed even after expanding a subdirectory
        console.log(`[Category click] Select category: ${category.name} (ID: ${category.id}, Level: ${level})`);
        selectCategory(category.id, category.name, level);
    });

    // right click menu
    div.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        // If there are multiple selected directories, display the batch menu（No matter which directory you click on）
        if (isCategoryMultiSelectMode && selectedCategoryIds.size > 0) {
            showCategoryBatchContextMenu(e);
        } else {
            // If not in multiple selections, display a single directory menu
            showContextMenu(e, category.id);
        }
    });

    // Keyboard events
    div.addEventListener('keydown', (e) => {
        // Enter key - Rename
        if (e.key === 'Enter' && !e.ctrlKey && !e.shiftKey) {
            e.preventDefault();
            if (isCategoryMultiSelectMode && selectedCategoryIds.size > 1) {
                showMessage('Renaming is not supported in multi-select mode', 'warning');
                return;
            }
            startInlineRename(div, category);
        }
        // Delete/Backspace - delete
        if (e.key === 'Delete' || e.key === 'Backspace') {
            e.preventDefault();
            if (isCategoryMultiSelectMode && selectedCategoryIds.size > 0) {
                confirmDeleteSelectedCategories();
            } else {
                confirmDeleteCategory(category.id);
            }
        }
        // Escape - Exit multiple selection
        if (e.key === 'Escape') {
            if (isCategoryMultiSelectMode) {
                exitCategoryMultiSelectMode();
            }
        }
    });

    // Add drag and drop functionality（Make directories draggable）- Support batch drag and drop
    setupCategoryDrag(div, category);

    // Add drag target function（Receive drag and drop of paper or table of contents）
    setupCategoryDropTarget(div, category);

    // Toggle to expand/fold
    const toggle = div.querySelector('.category-toggle');
    if (toggle) {
        toggle.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleCategoryChildren(container, category);
        });
    }

    // Add category items to container
    container.appendChild(div);

    // Add subcategory
    if (hasChildren) {
        const childrenDiv = document.createElement('div');
        childrenDiv.className = 'category-children collapsed';
        // Subcategory sorting: top > Others > by name
        const sortedChildren = [...category.children].sort((a, b) => {
            // Top directory priority
            if (a.pinned && !b.pinned) return -1;
            if (!a.pinned && b.pinned) return 1;
            // Then Others Table of contents
            if (a.name === 'Others') return -1;
            if (b.name === 'Others') return 1;
            // Last sorted by name
            return (a.name || '').localeCompare(b.name || '');
        });
        sortedChildren.forEach(child => {
            const childElement = createCategoryElement(child, level + 1);
            childrenDiv.appendChild(childElement);
        });
        container.appendChild(childrenDiv);
    }

    return container;
}

// Switch category sub-item display/hide
function toggleCategoryChildren(element, category) {
    const toggle = element.querySelector('.category-toggle');
    const children = element.querySelector('.category-children');

    if (children) {
        children.classList.toggle('collapsed');
        const isExpanded = !children.classList.contains('collapsed');
        if (toggle) {
            toggle.classList.toggle('expanded', isExpanded);
        }
    }
}

// Select category
function selectCategory(categoryId, categoryName, level = null) {
    // Remove previous selection
    document.querySelectorAll('.category-item.selected').forEach(item => {
        item.classList.remove('selected');
    });

    // Add selected state
    const categoryElement = document.querySelector(`[data-category-id="${categoryId}"]`);
    if (categoryElement) {
        categoryElement.classList.add('selected');
        // If not passed in level, obtained from element attributes
        if (level === null) {
            level = parseInt(categoryElement.dataset.level || '0', 10);
        }
    }

    currentCategoryId = categoryId;
    currentCategoryTitle.textContent = categoryName;

    // Check whether the category has subdirectories, and if so, recursively load papers in all subdirectories
    const category = findCategoryById(categories, categoryId);
    const hasChildren = category && category.children && category.children.length > 0;

    // If there are subdirectories, load them recursively；Otherwise, only the papers in the current directory will be loaded.
    const recursive = hasChildren;
    loadPapers(categoryId, recursive);

    // Clear the right information panel
    clearPaperInfo();
}

// Load paper list
// recursive: Whether to recursively load papers in all subdirectories（Used for first-level directories/Big catalog）
async function loadPapers(categoryId, recursive = false) {
    try {
        // if categoryId for null/undefined, call renderAllPapers replace
        if (!categoryId) {
            console.log('[loadPapers] categoryId is empty, call renderAllPapers');
            await renderAllPapers();
            return;
        }

        currentViewMode = 'category';
        currentCategoryId = categoryId;
        saveCurrentViewState();
        showInfoPanel();
        // hide"to-read list"Label
        const readingListLabel = document.getElementById('reading-list-label');
        if (readingListLabel) {
            readingListLabel.style.display = 'none';
        }
        // Clear selection in category tree
        document.querySelectorAll('.category-item.selected').forEach(item => item.classList.remove('selected'));
        // If a category is clicked, select it
        if (categoryId && categoryId !== 'root') {
            const categoryItem = document.querySelector(`.category-item[data-category-id="${categoryId}"]`);
            if (categoryItem) {
                categoryItem.classList.add('selected');
            }
        }
        // Use local occupancy to avoid flickering caused by global masking
        papersList.innerHTML = `
            <div class="empty-state" style="opacity:.7">
                <i class="fas fa-file-pdf"></i>
                <p>loading...</p>
            </div>
        `;

        // according to recursive Parameter decision API path
        const apiUrl = recursive
            ? `/api/papers/${categoryId}/recursive`
            : `/api/papers/${categoryId}`;

        const response = await fetch(apiUrl);
        if (!response.ok) {
            console.error(`Failed to load paper: ${response.status} ${response.statusText}`);
            showMessage('Failed to load paper', 'error');
            return;
        }
        papers = await response.json();
        // Make sure to read listIDCollection updated
        await updateReadingListCount();
        renderPapersList();
    } catch (error) {
        console.error('Failed to load papers:', error);
        showMessage('Failed to load papers', 'error');
    }
}

// Show to-read list
async function showReadingList(preloadedPapers = null) {
    try {
        clearPaperInfo();
        document.querySelectorAll('.paper-item.selected').forEach(item => item.classList.remove('selected'));
        hideInfoPanel();
        currentViewMode = 'reading-list';
        currentCategoryId = null; // Clear category selection
        saveCurrentViewState();
        // Clear selection in category tree
        document.querySelectorAll('.category-item.selected').forEach(item => item.classList.remove('selected'));
        // Update title
        const currentCategoryTitle = document.getElementById('current-category');
        if (currentCategoryTitle) {
            currentCategoryTitle.textContent = `to-read list (${readingListCount} Chapter)`;
        }
        // show"to-read list"Label
        const readingListLabel = document.getElementById('reading-list-label');
        if (readingListLabel) {
            readingListLabel.style.display = 'inline-block';
        }
        // Get the to-read list from the backend
        papersList.innerHTML = `
            <div class="empty-state" style="opacity:.7">
                <i class="fas fa-file-pdf"></i>
                <p>loading...</p>
            </div>
        `;

        if (preloadedPapers) {
            papers = preloadedPapers;
        } else {
            const response = await fetch('/api/reading-list');
            papers = await response.json();
        }

        // update count sumIDgather（Make sure to complete before rendering）
        readingListCount = papers.length;
        readingListPaperIds.clear();
        papers.forEach(p => readingListPaperIds.add(p.id));
        // renewUIshow
        const tiReadingCount = document.getElementById('ti-reading-count');
        if (tiReadingCount) {
            tiReadingCount.textContent = readingListCount;
        }
        const btnReading = document.getElementById('btn-show-reading-list');
        if (btnReading) {
            if (readingListCount > 0) {
                btnReading.classList.add('has-tasks');
            } else {
                btnReading.classList.remove('has-tasks');
            }
        }
        // If there is no paper, the empty status is displayed.
        if (papers.length === 0) {
            papersList.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-book-open"></i>
                    <p>Reading list is empty</p>
                </div>
            `;
            document.getElementById('sort-controls').style.display = 'none';
            return;
        }
        renderPapersList();
    } catch (error) {
        console.error('Failed to load reading list:', error);
        showMessage('Failed to load reading list', 'error');
    }
}

// Update the to-read list count andIDgather
async function updateReadingListCount() {
    try {
        const response = await fetch('/api/reading-list');
        const papers = await response.json();
        readingListCount = papers.length;
        // renewIDgather
        readingListPaperIds.clear();
        papers.forEach(p => readingListPaperIds.add(p.id));

        const tiReadingCount = document.getElementById('ti-reading-count');
        if (tiReadingCount) {
            tiReadingCount.textContent = readingListCount;
        }
        const btnReading = document.getElementById('btn-show-reading-list');
        if (btnReading) {
            if (readingListCount > 0) {
                btnReading.classList.add('has-tasks');
            } else {
                btnReading.classList.remove('has-tasks');
            }
        }
        return papers;
    } catch (e) {
        console.error('Failed to update reading list count:', e);
        return null;
    }
}

// Add to Readling List
async function addToReadingList(paperId, event) {
    if (event) event.stopPropagation();
    try {
        const response = await fetch(`/api/reading-list/${paperId}/add`, {
            method: 'POST'
        });
        if (response.ok) {
            showMessage('Added to to-read list', 'success');
            // renewIDSets and counting
            readingListPaperIds.add(paperId);
            await updateReadingListCount();
            // If you are currently viewing a category list, update the display
            if (currentViewMode === 'category' && currentCategoryId) {
                renderPapersList();
            }
        } else {
            showMessage('Failed to add to reading list', 'error');
        }
    } catch (error) {
        console.error('Failed to add to reading list:', error);
        showMessage('Failed to add to reading list', 'error');
    }
}

// Remove paper from to-read list
async function removeFromReadingList(paperId, event) {
    if (event) event.stopPropagation();
    try {
        // Try removing it first to see if you need confirmation
        const response = await fetch(`/api/reading-list/${paperId}/remove`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ delete_files: false })
        });

        const data = await response.json();

        if (data.requires_confirmation) {
            // Confirmation of deletion is required and a pop-up window will be displayed.
            const confirmed = confirm(data.message || 'This paper has not been moved into any folder yet. Delete the PDF file, AI analysis and AI translation as well?');
            if (confirmed) {
                // User confirms, deletes file
                const deleteResponse = await fetch(`/api/reading-list/${paperId}/remove`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ delete_files: true })
                });
                const deleteData = await deleteResponse.json();
                if (deleteData.success) {
                    showMessage('Removed from reading list and deleted related files', 'success');
                    // renewIDSets and counting
                    readingListPaperIds.delete(paperId);
                    const updatedPapers = await updateReadingListCount();
                    // If you are currently viewing the to-read list, refresh the list
                    if (currentViewMode === 'reading-list') {
                        showReadingList(updatedPapers);
                    } else if (currentViewMode === 'category' && currentCategoryId) {
                        // If in the category list, update the display
                        renderPapersList();
                    }
                } else {
                    showMessage(deleteData.error || 'Delete failed', 'error');
                }
            }
            // User cancels without taking any action
            return;
        }

        if (response.ok && data.success) {
            const message = data.deleted_files
                ? 'Removed from reading list and deleted related files'
                : 'Removed from reading list';
            showMessage(message, 'success');
            // renewIDSets and counting
            readingListPaperIds.delete(paperId);
            const updatedPapers = await updateReadingListCount();
            if (currentViewMode === 'reading-list' && currentPaperId === paperId) {
                clearPaperInfo();
                document.querySelectorAll('.paper-item.selected').forEach(item => item.classList.remove('selected'));
                hideInfoPanel();
            }
            // If you are currently viewing the to-read list, refresh the list
            if (currentViewMode === 'reading-list') {
                showReadingList(updatedPapers);
            } else if (currentViewMode === 'category' && currentCategoryId) {
                // If in the category list, update the display
                renderPapersList();
            }
        } else if (!data.requires_confirmation) {
            // If it is not the case that requires confirmation, an error will be displayed.
            showMessage(data.error || 'Failed to remove from reading list', 'error');
        }
    } catch (error) {
        console.error('Failed to remove from reading list:', error);
        showMessage('Failed to remove from reading list', 'error');
    }
}

// generate thesis itemsHTML（table layout）
function generatePaperItemHTML(paper, showCheckbox = false) {
    const isSelected = selectedPaperIds.has(paper.id);

    // icon column
    const iconCol = `
        <div class="paper-col-icon">
            ${showCheckbox && isMultiSelectMode ? `<input type="checkbox" ${isSelected ? 'checked' : ''} data-check="1" style="margin-right: 6px;" />` : ''}
            <i class="fas fa-file-pdf" style="color: #dc3545; font-size: 16px;"></i>
        </div>
    `;

    // title bar（Includes reading time）
    const readTimeText = getTotalReadTimeText(paper);
    const titleCol = `
        <div class="paper-col-title" title="${paper.title || paper.filename}">
            ${paper.title || paper.filename}${readTimeText}
        </div>
    `;

    // date column
    const uploadDate = new Date(paper.upload_date).toLocaleDateString('en-US');
    const arxivDate = paper.arxiv_published_date ? new Date(paper.arxiv_published_date).toLocaleDateString('en-US') : null;
    const dateCol = `
        <div class="paper-col-date">
            ${uploadDate}${arxivDate ? '<br>arXiv: ' + arxivDate : ''}
        </div>
    `;

    // AItranslation column
    const tStatus = translationStatus[paper.id];
    let translateCol = '';
    if (tStatus && tStatus.status === 'translating') {
        const progress = clampProgress(tStatus.progress ?? 0);
        translateCol = `<div class="paper-col-action">
            <div style="display: flex; flex-direction: column; width: 100%; gap: 4px;">
                <div style="display: flex; justify-content: space-between; align-items: center; line-height: 1;">
                    <div style="display: flex; align-items: center; gap: 4px;">
                        <button class="paper-action-log" onclick="showTranslationLogs('${paper.id}', event)" title="View logs"><i class="fas fa-list"></i></button>
                        <span style="font-size: 11px; color: #007bff; font-weight: 500;">${Math.round(progress)}%</span>
                    </div>
                    <button onclick="cancelTranslationFromStatus('${paper.id}', event)" title="Cancel translation" style="font-size: 10px; padding: 2px 6px; border: 1px solid #dc3545; background: #fff; color: #dc3545; border-radius: 4px; cursor: pointer; display: flex; align-items: center; gap: 3px; line-height: 1;">
                        <i class="fas fa-stop" style="font-size: 8px;"></i> Cancel
                    </button>
                </div>
                <div class="progress-bar-container translation-progress-bar" style="height: 4px; background: #e9ecef; border-radius: 2px;">
                    <div class="progress-bar" style="width: ${progress}%; background-color: #007bff; height: 100%; border-radius: 2px; transition: width 0.3s;"></div>
                </div>
            </div>
        </div>`;
    } else if (tStatus && tStatus.status === 'queued') {
        const currentIndex = translationQueue.indexOf(paper.id) + 1;
        const queueText = currentIndex > 0 ? `Queue ${currentIndex}` : 'Queueing';
        translateCol = `<div class="paper-col-action">
            <div style="display: flex; flex-direction: column; width: 100%; gap: 4px;">
                <div style="display: flex; justify-content: space-between; align-items: center; line-height: 1;">
                    <span style="font-size: 11px; color: #ffc107; display: flex; align-items: center; gap: 4px;">
                        <i class="fas fa-clock" style="font-size: 10px;"></i> ${queueText}
                    </span>
                    <button onclick="cancelTranslationFromQueue('${paper.id}', event)" title="Cancel queue" style="font-size: 10px; padding: 2px 6px; border: 1px solid #dc3545; background: #fff; color: #dc3545; border-radius: 4px; cursor: pointer; display: flex; align-items: center; gap: 3px; line-height: 1;">
                        <i class="fas fa-times" style="font-size: 8px;"></i> Cancel
                    </button>
                </div>
            </div>
        </div>`;
    } else if (paper.has_chinese_version) {
        translateCol = `<div class="paper-col-action"><button class="paper-col-btn view chinese" onclick="openChineseVersion('${paper.id}', event)"><i class="fas fa-language"></i> Chinese version</button></div>`;
    } else {
        translateCol = `<div class="paper-col-action"><button class="paper-col-btn translate icon-only" onclick="requestTranslation('${paper.id}', event)" title="AI Translate"><i class="fas fa-language"></i></button></div>`;
    }

    // AIInterpret columns
    const aStatus = analysisStatus[paper.id];
    let analyzeCol = '';
    if (aStatus && aStatus.status === 'analyzing') {
        const progress = clampProgress(aStatus.progress ?? 0);
        analyzeCol = `<div class="paper-col-action">
            <div style="display: flex; flex-direction: column; width: 100%; gap: 4px;">
                <div style="display: flex; justify-content: space-between; align-items: center; line-height: 1;">
                    <div style="display: flex; align-items: center; gap: 4px;">
                         <button class="paper-action-log" onclick="showAnalysisLogs('${paper.id}', event)" title="View logs"><i class="fas fa-list"></i></button>
                        <span style="font-size: 11px; color: #6f42c1; font-weight: 500;">${Math.round(progress)}%</span>
                    </div>
                    <button onclick="cancelAnalysis('${paper.id}', event)" title="Cancel interpretation" style="font-size: 10px; padding: 2px 6px; border: 1px solid #dc3545; background: #fff; color: #dc3545; border-radius: 4px; cursor: pointer; display: flex; align-items: center; gap: 3px; line-height: 1;">
                        <i class="fas fa-stop" style="font-size: 8px;"></i> Cancel
                    </button>
                </div>
                <div class="progress-bar-container" style="height: 4px; background: #e9ecef; border-radius: 2px; width: 100%;">
                    <div class="progress-bar" style="width: ${progress}%; background-color: #6f42c1; height: 100%; border-radius: 2px; transition: width 0.3s;"></div>
                </div>
            </div>
        </div>`;
    } else if (aStatus && aStatus.status === 'queued') {
        const currentIndex = analysisQueue.indexOf(paper.id) + 1;
        const queueText = currentIndex > 0 ? `Queue ${currentIndex}` : 'Queueing';
        analyzeCol = `<div class="paper-col-action">
            <div style="display: flex; flex-direction: column; width: 100%; gap: 4px;">
                <div style="display: flex; justify-content: space-between; align-items: center; line-height: 1;">
                    <span style="font-size: 11px; color: #ffc107; display: flex; align-items: center; gap: 4px;">
                        <i class="fas fa-clock" style="font-size: 10px;"></i> ${queueText}
                    </span>
                    <button onclick="cancelAnalysis('${paper.id}', event)" title="Cancel queue" style="font-size: 10px; padding: 2px 6px; border: 1px solid #dc3545; background: #fff; color: #dc3545; border-radius: 4px; cursor: pointer; display: flex; align-items: center; gap: 3px; line-height: 1;">
                        <i class="fas fa-times" style="font-size: 8px;"></i> Cancel
                    </button>
                </div>
            </div>
        </div>`;
    } else if (paper.has_analysis_result) {
        analyzeCol = `<div class="paper-col-action"><button class="paper-col-btn view analysis" onclick="viewAnalysisResult('${paper.id}', event)"><i class="fas fa-brain"></i> AI Interpretation</button></div>`;
    } else {
        analyzeCol = `<div class="paper-col-action"><button class="paper-col-btn analyze icon-only" onclick="requestAnalysis('${paper.id}', event)" title="AI Interpretation"><i class="fas fa-brain"></i></button></div>`;
    }

    // AI Interaction column
    const chatCol = `<div class="paper-col-action"><button class="paper-col-btn chat" onclick="openChat('${paper.id}', event)"><i class="fas fa-comments"></i> Chat</button></div>`;

    // Column to be read
    const isInReadingList = readingListPaperIds.has(paper.id);
    let readingCol = '';
    if (isInReadingList) {
        readingCol = `<div class="paper-col-action"><button class="paper-col-btn reading in-list icon-only" onclick="removeFromReadingList('${paper.id}', event)" title="Remove from to-read list"><i class="fas fa-times"></i></button></div>`;
    } else {
        readingCol = `<div class="paper-col-action"><button class="paper-col-btn reading icon-only" onclick="addToReadingList('${paper.id}', event)" title="Add to Readling List"><i class="fas fa-book-open"></i></button></div>`;
    }

    return iconCol + titleCol + dateCol + translateCol + analyzeCol + chatCol + readingCol;
}

// Render paper list
function renderPapersList() {
    const sortControls = document.getElementById('sort-controls');

    if (papers.length === 0) {
        papersList.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-file-pdf"></i>
                <p>There are currently no items in this category PDF document</p>
                <p style="font-size: 12px; margin-top: 10px;">Drag the file to the upload area on the left or click the upload button</p>
            </div>
        `;
        sortControls.style.display = 'none';
        return;
    }

    // Show sort controls
    sortControls.style.display = 'flex';

    // Get the current sorting method
    const sortBy = document.getElementById('sort-by').value;

    // sort papers
    const sortedPapers = sortPapers([...papers], sortBy);
    // Save the current sorting for easy shift choose
    window.__currentSortedPapers = sortedPapers.map(p => p.id);

    // Add header
    papersList.innerHTML = `
        <div class="paper-header">
            <div class="paper-header-col"></div>
            <div class="paper-header-col">title<div class="paper-header-resizer" data-col="1"></div></div>
            <div class="paper-header-col">date<div class="paper-header-resizer" data-col="2"></div></div>
            <div class="paper-header-col">AI translate<div class="paper-header-resizer" data-col="3"></div></div>
            <div class="paper-header-col">AI Interpretation<div class="paper-header-resizer" data-col="4"></div></div>
            <div class="paper-header-col">AI Interaction<div class="paper-header-resizer" data-col="5"></div></div>
            <div class="paper-header-col">To be read</div>
        </div>
    `;

    // Add column width adjustment function
    setupColumnResizing();

    sortedPapers.forEach(paper => {
        const div = document.createElement('div');
        const isSelected = selectedPaperIds.has(paper.id);
        // If the currently selected paper is this, add selected kind
        const isCurrentSelected = currentPaperId === paper.id;
        div.className = `paper-item${isSelected ? ' multi-selected' : ''}${isCurrentSelected ? ' selected' : ''}`;
        div.dataset.paperId = paper.id;
        div.innerHTML = generatePaperItemHTML(paper, true);

        div.addEventListener('click', (e) => {
            if (draggedPaper) { e.preventDefault(); return; }
            if (isMultiSelectMode) {
                handleMultiSelectClick(e, paper.id);
            } else {
                selectPaper(paper.id);
            }
        });

        // Add right-click menu
        div.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            showPaperContextMenu(e, paper.id);
        });

        // Double click to open PDF reader（Ignore double click on button）
        div.addEventListener('dblclick', (e) => {
            // If you double-click a button or an element within a button, opening will not be triggered.
            if (e.target.closest('button') || e.target.closest('.paper-col-btn')) {
                return;
            }
            e.preventDefault();
            openPDFViewer(paper.id);
        });

        // Add drag and drop functionality
        setupPaperDrag(div, paper);

        papersList.appendChild(div);
    });
}

// Select paper
function selectPaper(paperId) {
    // Set up first currentPaperId,so renderPapersList will be automatically selected
    currentPaperId = paperId;

    // Remove previous selection
    document.querySelectorAll('.paper-item.selected').forEach(item => {
        item.classList.remove('selected');
    });

    // Add selected state
    const paperElement = document.querySelector(`.paper-item[data-paper-id="${paperId}"]`);
    if (paperElement) {
        paperElement.classList.add('selected');
    } else {
        // If the element does not exist, it may be that the list has not been rendered yet.
        // Trigger a re-render（if the list already exists）
        if (papers.length > 0) {
            renderPapersList();
        }
    }

    showInfoPanel();
    loadPaperInfo(paperId);
    markPaperViewed(paperId);
}

// Load paper information
async function loadPaperInfo(paperId) {
    try {
        const panel = document.querySelector('.info-panel');
        if (panel) panel.classList.remove('wide');
        const response = await fetch(`/api/paper/${paperId}`);
        const paper = await response.json();
        renderPaperInfo(paper);
    } catch (error) {
        console.error('Failed to load paper info:', error);
        showMessage('Failed to load paper info', 'error');
    }
}

// Render paper information（Refactored version: compact+fold）
function renderPaperInfo(paper) {
    // Helper function: formattingarXivdate（Remove duplicate years）
    const formatArxivDate = (dateString) => {
        if (!dateString) return '';
        try {
            const date = new Date(dateString);
            const year = date.getFullYear();
            const month = String(date.getMonth() + 1).padStart(2, '0');
            const day = String(date.getDate()).padStart(2, '0');
            return `${year}/${month}/${day}`;
        } catch (e) {
            return dateString;
        }
    };

    // Helper function: Create expandable text blocks
    const createExpandableTextBlock = (label, content, field, multiline = false, defaultExpanded = false, editable = true) => {
        if (!content) return '';

        // Simple judgment whether expansion is needed: check the text length or the number of line breaks
        // For a single line of text, it may need to be expanded if it exceeds a certain length.
        // For multi-line text, if more than3row needs to be expanded
        let needsExpand = false;
        if (multiline) {
            const lines = content.split('\n');
            needsExpand = lines.length > 3 || content.length > 200;
        } else {
            // A single line of text may need to be expanded if it is too long
            needsExpand = content.length > 100;
        }

        const isCollapsed = needsExpand && !defaultExpanded;
        const collapsedClass = isCollapsed ? 'text-collapsed' : '';
        const editableClass = editable ? 'editable' : '';
        const editableAttr = editable ? 'contenteditable="true"' : '';

        return `
            <div class="info-section compact" data-field="${field}">
                <div class="info-header">
                    <span class="info-label">${label}</span>
                </div>
                <div class="info-content">
                    <div class="info-value text-block ${collapsedClass} ${editableClass}" 
                         data-field="${field}" 
                         ${editableAttr}
                         data-full-text="${escapeHtml(content)}"
                         style="${multiline ? 'white-space: pre-wrap;' : ''}">${escapeHtml(content || '')}</div>
                    ${needsExpand ? `
                    <div class="text-expand-btn" onclick="toggleTextExpand(this)" style="display: ${isCollapsed ? 'block' : 'none'}">
                        <i class="fas fa-chevron-down"></i> Expand
                    </div>
                    <div class="text-collapse-btn" onclick="toggleTextCollapse(this)" style="display: ${isCollapsed ? 'none' : 'block'}">
                        <i class="fas fa-chevron-up"></i> close
                    </div>
                    ` : ''}
                </div>
            </div>
        `;
    };

    // HTMLescape function
    const escapeHtml = (text) => {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    };

    paperInfo.innerHTML = `
        <div class="paper-info-container compact-mode">
            <!-- Basic information -->
            ${createExpandableTextBlock('title', paper.title, 'title', false, false, true)}
            ${createExpandableTextBlock('author', paper.authors, 'authors', false, false, true)}
            ${paper.arxiv_id || paper.arxiv_url ? `
            <div class="info-section compact">
                <div class="info-header">
                    <span class="info-label">URL</span>
                </div>
                <div class="info-content">
                    <div class="info-value">
                        ${paper.arxiv_url ? `
                        <a href="${paper.arxiv_url}" target="_blank" rel="noopener noreferrer" class="paper-url-link">
                            <i class="fas fa-external-link-alt"></i> ${paper.arxiv_url}
                        </a>
                        ` : paper.arxiv_id ? `
                        <a href="https://arxiv.org/abs/${paper.arxiv_id}" target="_blank" rel="noopener noreferrer" class="paper-url-link">
                            <i class="fas fa-external-link-alt"></i> https://arxiv.org/abs/${paper.arxiv_id}
                        </a>
                        ` : '<span style="color: #999; font-style: italic;">none URL</span>'}
                    </div>
                </div>
            </div>
            ` : ''}
            <div class="info-section compact">
                <div class="info-header">
                    <span class="info-label">Github</span>
                </div>
                <div class="info-content">
                    <div class="info-value editable" contenteditable="true" data-field="github" data-url-field="true" data-full-text="${escapeHtml(paper.github || '')}">
                        ${paper.github ? `
                            <a href="${paper.github.startsWith('http') ? paper.github : 'https://' + paper.github}" target="_blank" rel="noopener noreferrer" class="paper-url-link" onclick="event.stopPropagation();">
                                <i class="fab fa-github"></i> ${paper.github}
                            </a>
                        ` : '<span style="color: #999; font-style: italic;">Click to add GitHub repository URL</span>'}
                    </div>
                </div>
            </div>
            <div class="info-section compact">
                <div class="info-header">
                    <span class="info-label">Homepage</span>
                </div>
                <div class="info-content">
                    <div class="info-value editable" contenteditable="true" data-field="homepage" data-url-field="true" data-full-text="${escapeHtml(paper.homepage || '')}">
                        ${paper.homepage ? `
                            <a href="${paper.homepage.startsWith('http') ? paper.homepage : 'https://' + paper.homepage}" target="_blank" rel="noopener noreferrer" class="paper-url-link" onclick="event.stopPropagation();">
                                <i class="fas fa-home"></i> ${paper.homepage}
                            </a>
                        ` : '<span style="color: #999; font-style: italic;">Click to add project homepage URL</span>'}
                    </div>
                </div>
            </div>
            ${createExpandableTextBlock('Affiliation', paper.affiliation, 'affiliation', true, false, true)}
            
            <!-- Time info -->
            <div class="info-section compact">
                <div class="info-header">
                    <span class="info-label">Time</span>
                </div>
                <div class="info-content">
                    <div class="info-value compact-text">
                        ${paper.arxiv_published_date ? `<span><i class="fas fa-clock"></i> arXiv: ${formatArxivDate(paper.arxiv_published_date)}</span>` : ''}
                        ${paper.year && !paper.arxiv_published_date ? `<span><i class="fas fa-calendar"></i> ${paper.year}</span>` : ''}
                    </div>
                </div>
            </div>
            
            <!-- Abstract -->
            ${createExpandableTextBlock('Abstract', paper.abstract, 'abstract', true, false, true)}
            
            <!-- BibTeX -->
            ${paper.bibtex ? `
            <div class="info-section compact collapsed" data-field="bibtex">
                <div class="info-header" onclick="toggleInfoSection(this)">
                    <span class="info-label">BibTeX</span>
                    <button class="btn-icon" onclick="event.stopPropagation(); copyBibtex('${paper.id}')" title="Copy">
                        <i class="fas fa-copy"></i>
                    </button>
                    <i class="fas fa-chevron-down toggle-icon"></i>
                </div>
                <div class="info-content">
                    <pre class="bibtex-content" id="bibtex-${paper.id}">${escapeHtml(paper.bibtex || '')}</pre>
                </div>
            </div>
            ` : ''}
            
            <!-- Notes -->
            <div class="info-section compact ${paper.notes ? '' : 'collapsed'}" data-field="notes">
                <div class="info-header" onclick="toggleInfoSection(this)">
                    <span class="info-label">Notes</span>
                    <i class="fas fa-chevron-down toggle-icon"></i>
                </div>
                <div class="info-content">
                    <div class="info-value text-block editable notes-editable" 
                         data-field="notes" 
                         contenteditable="true"
                         data-full-text="${escapeHtml(paper.notes || '')}"
                         data-placeholder="Click to add notes..."
                         style="white-space: pre-wrap; min-height: 40px;">${escapeHtml(paper.notes || '')}</div>
                </div>
            </div>
            
            <!-- Chinese version -->
            ${paper.has_chinese_version ? `
            <div class="info-section compact">
                <div class="info-content">
                    <button class="btn btn-primary btn-block" onclick="openChineseVersion('${paper.id}')">
                        <i class="fas fa-language"></i> Open Chinese version
                    </button>
                </div>
            </div>
            ` : ''}
        </div>
    `;

    // Add edit event listener（Only for editable fields）
    paperInfo.querySelectorAll('.editable').forEach(element => {
        // URL Field special treatment（github, homepage）
        if (element.dataset.urlField === 'true') {
            // When focused: extract plain text URL（If there is a link）
            element.addEventListener('focus', () => {
                const link = element.querySelector('a');
                if (link) {
                    // Extract linked href or text content
                    let url = link.href || link.textContent.trim();
                    // Remove protocol prefix（if there is）
                    url = url.replace(/^https?:\/\//, '').replace(/^\/\//, '');
                    // Remove icons and extra spaces
                    url = url.replace(/^\s*[^\s]+\s+/, '').trim();
                    element.textContent = url;
                } else {
                    // If there is no link, check if there is placeholder text
                    const text = element.textContent.trim();
                    if (text && !text.includes('Click to add')) {
                        element.textContent = text;
                    } else {
                        element.textContent = '';
                    }
                }
            });

            // When focus is lost: save and re-render as link
            element.addEventListener('blur', () => {
                let content = element.textContent.trim();

                // If empty or contains placeholder Text, holds empty string
                if (!content || content.includes('Click to add')) {
                    content = '';
                }

                // keep
                savePaperField(paper.id, element.dataset.field, content);

                // Re-render paper information to show links
                if (currentPaperId) {
                    loadPaperInfo(currentPaperId);
                }
            });
        } else {
            // Common field processing
            element.addEventListener('blur', () => {
                // Get content and save
                const content = element.textContent.trim();
                savePaperField(paper.id, element.dataset.field, content);

                // Remarks column placeholder Processing: If empty, clear the content to display placeholder
                if (element.dataset.field === 'notes' && !content) {
                    element.textContent = '';
                }
            });
        }

        element.addEventListener('keydown', (e) => {
            const isMultiline = ['abstract', 'notes'].includes(element.dataset.field);
            if (e.key === 'Enter' && !e.shiftKey && !isMultiline) {
                e.preventDefault();
                element.blur();
            }
        });

        // Remarks column placeholder deal with
        if (element.dataset.field === 'notes') {
            // Initialization: If empty, clear the content to display placeholder
            if (!element.textContent.trim()) {
                element.textContent = '';
            }

            // When focused: if empty, make sure you can enter
            element.addEventListener('focus', () => {
                // placeholder will pass CSS auto-hide
            });
        }
    });

    // Initialize the expansion of the text block/folded state
    paperInfo.querySelectorAll('.text-block').forEach(block => {
        const fullText = block.dataset.fullText || block.textContent;
        block.dataset.fullText = fullText;
    });
}

// Toggle the folded state of the information area
function toggleInfoSection(header) {
    const section = header.closest('.info-section');
    section.classList.toggle('collapsed');
}

// Toggle text expansion/folded state
function toggleTextExpand(btn) {
    const content = btn.previousElementSibling;
    if (!content || !content.classList.contains('text-block')) return;

    // Expand
    content.classList.remove('text-collapsed');
    btn.style.display = 'none';

    // Show collapse button
    const collapseBtn = content.parentElement.querySelector('.text-collapse-btn');
    if (collapseBtn) {
        collapseBtn.style.display = 'block';
    }
}

// Collapse text
function toggleTextCollapse(btn) {
    const content = btn.previousElementSibling.previousElementSibling;
    if (!content || !content.classList.contains('text-block')) return;

    content.classList.add('text-collapsed');
    btn.style.display = 'none';

    // Show expand button
    const expandBtn = content.parentElement.querySelector('.text-expand-btn');
    if (expandBtn) {
        expandBtn.style.display = 'block';
    }
}

// copy BibTeX
function copyBibtex(paperId) {
    const bibtexElem = document.getElementById(`bibtex-${paperId}`);
    if (bibtexElem) {
        const text = bibtexElem.textContent;
        navigator.clipboard.writeText(text).then(() => {
            showMessage('BibTeX Copied to clipboard', 'success', 2000);
        }).catch(err => {
            console.error('Copy failed:', err);
            showMessage('Copy failed', 'error');
        });
    }
}

// Save paper fields
async function savePaperField(paperId, field, value) {
    try {
        const response = await fetch(`/api/paper/${paperId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                [field]: value
            })
        });

        if (response.ok) {
            // Update local data
            const paper = papers.find(p => p.id === paperId);
            if (paper) {
                paper[field] = value;
                // If the title is updated, re-render the paper list
                if (field === 'title') {
                    renderPapersList();
                    selectPaper(paperId); // Reselect
                }
            }
        } else {
            showMessage('Save failed', 'error');
        }
    } catch (error) {
        console.error('Failed to save paper information:', error);
        showMessage('Save failed', 'error');
    }
}

// Clear paper information
function clearPaperInfo() {
    paperInfo.innerHTML = `
        <div class="empty-state">
            <i class="fas fa-file-alt"></i>
            <p>Select a paper to view details</p>
        </div>
    `;
    currentPaperId = null;
}

// Set up drag and drop upload
function setupDragAndDrop() {
    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }

    // Add drag and drop support to category tree
    categoryTree.addEventListener('dragover', (e) => {
        preventDefaults(e);

        // Check whether the dragged category is（Single or batch）
        const isDraggingCategory = draggedCategory || draggedCategories.length > 0;

        if (isDraggingCategory) {
            // If the dragging is a category, check whether it is in a certaincategory-itemsuperior
            const categoryItem = e.target.closest('.category-item');
            if (!categoryItem) {
                // In an empty space, allow movement to the root directory
                e.dataTransfer.dropEffect = 'move';
                categoryTree.classList.add('drag-over-root');
                return;
            }
        }

        // Handles file drag and drop by default
        e.dataTransfer.dropEffect = 'copy';
        const categoryItem = e.target.closest('.category-item');
        if (categoryItem) {
            categoryItem.classList.add('drag-over');
        }
    });

    categoryTree.addEventListener('dragleave', (e) => {
        const categoryItem = e.target.closest('.category-item');
        if (categoryItem) {
            categoryItem.classList.remove('drag-over');
        }
        // Check if it really leftcategoryTree（instead of going into child elements）
        const rect = categoryTree.getBoundingClientRect();
        const x = e.clientX;
        const y = e.clientY;

        if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) {
            categoryTree.classList.remove('drag-over-root');
        }
    });

    categoryTree.addEventListener('drop', (e) => {
        preventDefaults(e);

        // Check whether the dragged category is（Single or batch）
        const isDraggingCategory = draggedCategory || draggedCategories.length > 0;

        if (isDraggingCategory) {
            const categoryItem = e.target.closest('.category-item');

            // if not in anycategory-itemon, the instructions are dragged to a blank area and moved to the root directory.
            if (!categoryItem) {
                categoryTree.classList.remove('drag-over-root');

                // Batch move
                if (draggedCategories.length > 0) {
                    console.log(`Batch placement ${draggedCategories.length} directories to the root directory`);
                    moveCategories(draggedCategories.map(c => c.id), 'root');
                }
                // single move
                else if (draggedCategory) {
                    console.log('Place the directory into the root directory:', draggedCategory.name);
                    moveCategory(draggedCategory.id, 'root');
                }
                return;
            }
            // if incategory-itemon, bysetupCategoryDropTargetdeal with
            return;
        }

        // Handle file drag and drop
        const categoryItem = e.target.closest('.category-item');
        if (categoryItem) {
            categoryItem.classList.remove('drag-over');
            const categoryId = categoryItem.dataset.categoryId;
            if (categoryId) {
                handleFilesWithCategory(e.dataTransfer.files, categoryId);
            }
        }
    });

    // Add drag and drop support to the paper list area
    papersList.addEventListener('dragover', (e) => {
        preventDefaults(e);
        e.dataTransfer.dropEffect = 'copy';
        // Support drag-and-drop upload of to-be-read list
        if (currentViewMode === 'reading-list' || currentCategoryId) {
            papersList.classList.add('drag-over');
        }
    });

    papersList.addEventListener('dragleave', (e) => {
        papersList.classList.remove('drag-over');
    });

    papersList.addEventListener('drop', (e) => {
        preventDefaults(e);
        papersList.classList.remove('drag-over');
        // Support drag-and-drop upload of to-be-read list
        if (currentViewMode === 'reading-list') {
            handleFilesWithCategory(e.dataTransfer.files, 'reading_list_temp');
        } else if (currentCategoryId) {
            handleFilesWithCategory(e.dataTransfer.files, currentCategoryId);
        } else {
            showMessage('Please select a category first', 'warning');
        }
    });

    // The upload area in the lower left corner has been removed: only bind if it exists（Compatible with oldDOM）
    if (uploadZone) {
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            uploadZone.addEventListener(eventName, preventDefaults, false);
        });
        ['dragenter', 'dragover'].forEach(eventName => {
            uploadZone.addEventListener(eventName, () => {
                uploadZone.classList.add('dragover');
            }, false);
        });
        ['dragleave', 'drop'].forEach(eventName => {
            uploadZone.addEventListener(eventName, () => {
                uploadZone.classList.remove('dragover');
            }, false);
        });
        uploadZone.addEventListener('drop', (e) => {
            // Support drag-and-drop upload of to-be-read list
            if (currentViewMode === 'reading-list') {
                handleFilesWithCategory(e.dataTransfer.files, 'reading_list_temp');
            } else if (currentCategoryId) {
                handleFilesWithCategory(e.dataTransfer.files, currentCategoryId);
            } else {
                showMessage('Please select a category first', 'warning');
            }
        }, false);
        uploadZone.addEventListener('click', () => {
            // Supports click-to-upload of to-read lists
            if (currentViewMode === 'reading-list') {
                fileInput.click();
            } else if (currentCategoryId) {
                fileInput.click();
            } else {
                showMessage('Please select a category first', 'warning');
            }
        });
    }
}

// Handle file selection
function handleFileSelect(e) {
    const files = e.target.files;
    // Support file selection and upload from the to-be-read list
    if (currentViewMode === 'reading-list') {
        handleFilesWithCategory(files, 'reading_list_temp');
    } else if (currentCategoryId) {
        handleFilesWithCategory(files, currentCategoryId);
    } else {
        showMessage('Please select a category first', 'warning');
    }
}

// Handle file uploads（With classificationID）
function handleFilesWithCategory(files, categoryId) {
    Array.from(files).forEach(file => {
        if (file.type === 'application/pdf') {
            uploadFile(file, categoryId);
        } else {
            showMessage(`document ${file.name} no PDF Format`, 'warning');
        }
    });
}

// use PDF.js Parse metadata and upload
async function uploadFile(file, categoryId) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('category_id', categoryId);

    // No more front-end analysis, everything is handed over to the back-end for processing（Use font size + arXiv search）
    // This is more accurate and does not block user operations

    try {
        // 异步上传，完全静默处理，不显示任何提示
        fetch('/api/upload', {
            method: 'POST',
            body: formData
        }).then(response => response.json())
            .then(async result => {
                if (result.success) {
                    // Refresh silently without displaying success prompt

                    // Synchronously update category counts and to-be-read list counts
                    updateCategoriesData();
                    renderCategoryTreeWithState();
                    const updatedPapers = await updateReadingListCount();

                    // If uploaded to the currently selected category, refresh the list immediately（Show placeholder）
                    if (currentCategoryId === categoryId) {
                        loadPapers(currentCategoryId);
                    }
                    // If uploaded to the to-read list, refresh the to-read list
                    if (categoryId === 'reading_list_temp' && currentViewMode === 'reading-list') {
                        showReadingList(updatedPapers);
                    }

                    // Start background polling to check whether the metadata update is completed
                    if (result.paper && result.paper.id) {
                        // Use placeholders paper data as initial snapshot
                        const initialSnapshot = {
                            title: result.paper.title || '',
                            authors: result.paper.authors || '',
                            abstract: result.paper.abstract || '',
                            bibtex: result.paper.bibtex || '',
                            arxiv_id: result.paper.arxiv_id || '',
                        };
                        startPollingPaperUpdate(result.paper.id, categoryId, initialSnapshot);
                    }
                } else {
                    // Only show error on failure
                    showMessage(`Upload failed: ${result.error}`, 'error');
                }
            }).catch(error => {
                console.error('File upload failed:', error);
                showMessage(`${file.name} Upload failed`, 'error');
            });

        // Return immediately without blocking user operations
        return;

    } catch (error) {
        console.error('Upload request failed:', error);
        showMessage('Upload failed', 'error');
    }
}

// Polling to check for paper updates（For background metadata processing）
// initialSnapshot Can be an initial snapshot object or an initial title string（backwards compatible）
function startPollingPaperUpdate(paperId, categoryId, initialSnapshotOrTitle, maxAttempts = 20) {
    let attempts = 0;
    let previousSnapshot = null; // Save initial snapshot for comparison

    // Processing parameters: If it is a string, convert it to a snapshot object；If it is an object, use it directly
    if (typeof initialSnapshotOrTitle === 'string') {
        // Backward compatibility: if a string is passed in（title）, create a snapshot object
        previousSnapshot = {
            title: initialSnapshotOrTitle || '',
            authors: '',
            abstract: '',
            bibtex: '',
            arxiv_id: '',
        };
        console.log(`[polling] Start polling for paper updates: ${paperId}, initial title: ${initialSnapshotOrTitle}`);
    } else {
        // If the snapshot object is passed in, use it directly
        previousSnapshot = initialSnapshotOrTitle || {
            title: '',
            authors: '',
            abstract: '',
            bibtex: '',
            arxiv_id: '',
        };
        console.log(`[polling] Start polling for paper updates: ${paperId}, initial snapshot: title="${previousSnapshot.title}"`);
    }

    const checkUpdate = async () => {
        try {
            attempts++;

            // Get the latest information on the paper
            const response = await fetch(`/api/paper/${paperId}`);
            if (!response.ok) {
                console.log(`[polling] paper ${paperId} Does not exist or has been deleted`);
                return; // Stop polling
            }

            const paper = await response.json();
            const currentTitle = paper.title || '';

            // Create a current snapshot for comparison
            const currentSnapshot = {
                title: paper.title || '',
                authors: paper.authors || '',
                abstract: paper.abstract || '',
                bibtex: paper.bibtex || '',
                arxiv_id: paper.arxiv_id || '',
            };

            // Check if key fields have changed（not just title）
            const hasChanged =
                currentSnapshot.title !== previousSnapshot.title ||
                currentSnapshot.authors !== previousSnapshot.authors ||
                currentSnapshot.abstract !== previousSnapshot.abstract ||
                currentSnapshot.bibtex !== previousSnapshot.bibtex ||
                currentSnapshot.arxiv_id !== previousSnapshot.arxiv_id;

            console.log(`[polling] No. ${attempts} inspections: title="${currentTitle}"`);

            if (hasChanged) {
                console.log(`[polling] ✅ Paper update detected!`);
                if (currentSnapshot.title !== previousSnapshot.title) {
                    console.log(`[polling]    title: "${previousSnapshot.title}" → "${currentSnapshot.title}"`);
                }
                if (currentSnapshot.authors !== previousSnapshot.authors) {
                    console.log(`[polling]    author: "${previousSnapshot.authors}" → "${currentSnapshot.authors}"`);
                }
                if (currentSnapshot.abstract !== previousSnapshot.abstract) {
                    console.log(`[polling]    summary: updated`);
                }
                if (currentSnapshot.bibtex !== previousSnapshot.bibtex) {
                    console.log(`[polling]    BibTeX: updated`);
                }

                // If you are still in the same category（Or all papers view）, refresh the list
                if (currentCategoryId === categoryId) {
                    console.log(`[polling] Refresh paper list...`);
                    if (currentCategoryId) {
                        await loadPapers(currentCategoryId);
                    } else {
                        // if categoryId for null, the description is in"All papers"view
                        await renderAllPapers();
                    }

                    // If this paper is currently selected, refresh the details
                    if (currentPaperId === paperId) {
                        console.log(`[polling] Refresh paper details...`);
                        renderPaperInfo(paper);
                    }
                } else {
                    // Even if it is not in the current category, if this paper is selected, the details must be refreshed.
                    if (currentPaperId === paperId) {
                        console.log(`[polling] Refresh paper details（Across categories）...`);
                        renderPaperInfo(paper);
                    }
                }

                // Update classification tree（The file name may have changed）
                await updateCategoriesData();
                renderCategoryTreeWithState();

                console.log(`[polling] Update completed, stop polling`);
                return; // Update completed, stop polling
            }

            // If the maximum number of attempts has not been reached, continue polling
            if (attempts < maxAttempts) {
                setTimeout(checkUpdate, 2000); // 2Check again after seconds
            } else {
                console.log(`[polling] ⚠️ Maximum number of attempts reached (${maxAttempts}), stop polling`);
            }

        } catch (error) {
            console.error('[polling] ❌ Check for updates failed:', error);
            // Keep trying even if something goes wrong
            if (attempts < maxAttempts) {
                setTimeout(checkUpdate, 2000);
            }
        }
    };

    // Delay1Start first check in seconds（Give background processing some time, but not too long）
    // For upload scenarios, the background may complete quickly, so the delay should not be too long
    setTimeout(checkUpdate, 1000);
}

// use PDF.js Parse file metadata
async function parsePdfWithPdfjs(file, { maxPages = 5 } = {}) {
    if (!window['pdfjsLib']) return null;
    const blobUrl = URL.createObjectURL(file);
    try {
        const loadingTask = pdfjsLib.getDocument({ url: blobUrl });
        const pdf = await loadingTask.promise;
        const pages = Math.min(maxPages, pdf.numPages);
        let text = '';
        for (let i = 1; i <= pages; i++) {
            const page = await pdf.getPage(i);
            const content = await page.getTextContent();
            const strings = content.items.map(it => it.str);
            text += strings.join(' ') + '\n';
        }
        URL.revokeObjectURL(blobUrl);
        const normalized = normalizePdfText(text);
        const meta = extractMetadataFromText(normalized);
        return meta;
    } catch (e) {
        URL.revokeObjectURL(blobUrl);
        throw e;
    }
}

function normalizePdfText(text) {
    let t = text || '';
    t = t.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    t = t.replace(/[\t\f]+/g, ' ');
    t = t.replace(/\u00A0/g, ' ');
    t = t.replace(/\n{3,}/g, '\n\n');
    t = t.split('\n').map(l => l.trim()).join('\n');
    return t;
}

function extractMetadataFromText(text) {
    const title = extractTitle(text);
    const authors = extractAuthors(text);
    const affiliation = extractAffiliation(text);
    // The digest is changed to be passed by the backend arXiv API Obtain, no longer parsed here
    return { title, authors, affiliation };
}

function extractTitle(text) {
    const lines = text.split('\n');
    for (let i = 0; i < Math.min(10, lines.length); i++) {
        const line = lines[i].trim();
        if (line.length > 10 && line.length < 300 && /[A-Za-zone-饥]/.test(line)) {
            if (!/^page|vol|volume|issue|doi|arxiv/i.test(line) && !/@|\.com|\.org/.test(line)) {
                return line;
            }
        }
    }
    return '';
}

function extractAuthors(text) {
    const lines = text.split('\n');
    const patterns = [
        /^([A-Z][a-z]+ [A-Z][a-z]+(?:,\s*[A-Z][a-z]+ [A-Z][a-z]+)*)/, // John Smith, Jane Doe
        /^([A-Z]\.?\s*[A-Z][a-z]+(?:,\s*[A-Z]\.?\s*[A-Z][a-z]+)*)/
    ];
    for (let i = 0; i < Math.min(15, lines.length); i++) {
        const line = lines[i].trim();
        if (line.length < 5 || line.length > 200) continue;
        for (const p of patterns) {
            const m = line.match(p);
            if (m) return m[1];
        }
    }
    return '';
}

function extractAffiliation(text) {
    const lines = text.split('\n');
    const keys = /(university|college|institute|laboratory|lab|department|school|center|centre|research|academy|corporation|company|inc\.|ltd\.|google|microsoft|openai|anthropic|meta|stanford|mit|harvard|berkeley|cambridge|University|College|Institute|Laboratory|Institute)/i;
    const results = [];
    for (let i = 0; i < Math.min(25, lines.length); i++) {
        const line = lines[i].trim();
        if (line.length > 6 && line.length < 300 && keys.test(line)) {
            if (!/^(abstract|Summary|introduction|Introduction|keywords|Keywords)/i.test(line)) {
                if (!results.includes(line)) results.push(line);
            }
        }
    }
    return results.slice(0, 3).join('; ');
}

function extractAbstract(text) {
    const stop = /(keywords|index\s*terms|subjects?|introduction|background|materials\s+and\s+methods|methods|results|conclusions|references|acknowledg(e)?ments|Keywords|Introduction|Methods|Results|Conclusion|References)/i;
    const start = /(abstract|summary|Abstract|Summary)/i;
    const lines = text.split('\n');
    let started = false;
    const buf = [];
    for (const raw of lines) {
        const line = raw.trim();
        if (!started) {
            if (start.test(line)) {
                const after = line.replace(start, '').replace(/^[:\-\.]\s*/, '').trim();
                if (after) buf.push(after);
                started = true;
            }
            continue;
        }
        if (stop.test(line)) break;
        buf.push(line);
    }
    const candidate = buf.join(' ').replace(/\s+/g, ' ').trim();
    if (candidate.length >= 50) return candidate;
    // fallback: longest paragraph
    const paragraphs = text.split(/\n\s*\n/).map(p => p.replace(/\s+/g, ' ').trim());
    const cand2 = paragraphs.filter(p => p.length >= 120).sort((a, b) => b.length - a.length)[0] || '';
    return cand2;
}

// Extract from file name arXiv ID
function extractArxivIdFromName(name) {
    const base = (name || '').replace(/\.pdf$/i, '');
    // new style arXiv: YYMM.number vN optional, e.g. 2510.09608v1 or 2510.09608
    const m = base.match(/\b(\d{4}\.\d{4,5})(v\d+)?\b/i);
    if (m) return m[1] + (m[2] || '');
    // Compatible with prefixed writing arXiv:2510.09608v1
    const m2 = base.match(/arxiv[:\-\s]?(\d{4}\.\d{4,5})(v\d+)?/i);
    if (m2) return m2[1] + (m2[2] || '');
    return '';
}

// Set up modal box
function setupModal() {
    const closeBtn = modal.querySelector('.close');
    const cancelBtn = document.getElementById('modal-cancel');

    closeBtn.addEventListener('click', hideModal);
    cancelBtn.addEventListener('click', hideModal);

    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            hideModal();
        }
    });
}

// Show add category modal box
function showAddCategoryModal(parentId) {
    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');
    let confirmBtn = document.getElementById('modal-confirm');
    let cancelBtn = document.getElementById('modal-cancel');

    modalTitle.textContent = 'Add category';
    modalBody.innerHTML = `
        <div class="form-group">
            <label for="category-name">Category name</label>
            <input type="text" id="category-name" placeholder="Please enter the category name">
        </div>
    `;

    // Reset button listening to avoid conflicts with other pop-up windows
    const confirmClone = confirmBtn.cloneNode(true);
    const cancelClone = cancelBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(confirmClone, confirmBtn);
    cancelBtn.parentNode.replaceChild(cancelClone, cancelBtn);
    confirmBtn = document.getElementById('modal-confirm');
    cancelBtn = document.getElementById('modal-cancel');
    confirmBtn.style.display = 'inline-block';
    confirmBtn.textContent = 'confirm';
    cancelBtn.textContent = 'Cancel';

    confirmBtn.onclick = () => {
        const name = document.getElementById('category-name').value.trim();
        if (name) {
            addCategory(parentId, name);
            hideModal();
        } else {
            showMessage('Please enter the category name', 'warning');
        }
    };
    cancelBtn.onclick = () => hideModal();

    showModal();
    document.getElementById('category-name').focus();
    // Bind Enter key to submit
    const input = document.getElementById('category-name');
    input.addEventListener('keydown', (e) => {
        // Avoid input method candidates when they appear on the screen Enter treated as submitted
        if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229) {
            e.preventDefault();
            confirmBtn.click();
        }
    });
}

// Show rename category modal box
function showRenameCategoryModal(categoryId) {
    const category = findCategoryById(categories, categoryId);
    if (!category) return;

    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');
    const confirmBtn = document.getElementById('modal-confirm');

    modalTitle.textContent = 'Rename category';
    modalBody.innerHTML = `
        <div class="form-group">
            <label for="category-name">Category name</label>
            <input type="text" id="category-name" value="${category.name}">
        </div>
    `;

    confirmBtn.onclick = () => {
        const name = document.getElementById('category-name').value.trim();
        if (name && name !== category.name) {
            renameCategory(categoryId, name);
            hideModal();
        } else if (!name) {
            showMessage('Please enter the category name', 'warning');
        } else {
            hideModal();
        }
    };

    showModal();
    const input = document.getElementById('category-name');
    input.focus();
    input.select();
}

// Show modal box
function showModal() {
    modal.classList.add('show');
}

// Hide modal box
function hideModal() {
    modal.classList.remove('show');
}

// Add category
async function addCategory(parentId, name) {
    try {
        const response = await fetch('/api/categories', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                parent_id: parentId,
                name: name
            })
        });

        const result = await response.json();

        if (result.success) {
            showMessage('Category added successfully', 'success');
            // Update local data instead of reloading the entire tree
            await updateCategoriesData();
            // Keep expanded and selected
            await renderCategoryTreeWithState();
        } else {
            showMessage(`Add failed: ${result.error}`, 'error');
        }
    } catch (error) {
        console.error('Failed to add category:', error);
        showMessage('Failed to add category', 'error');
    }
}

// Rename category
async function renameCategory(categoryId, newName) {
    try {
        const response = await fetch(`/api/categories/${categoryId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                name: newName
            })
        });

        const result = await response.json();

        if (result.success) {
            showMessage('Category renamed successfully', 'success');
            // Update local data instead of reloading the entire tree
            await updateCategoriesData();
            // Keep expanded and selected
            await renderCategoryTreeWithState();
        } else {
            showMessage(`Rename failed: ${result.error}`, 'error');
        }
    } catch (error) {
        console.error('Failed to rename category:', error);
        showMessage('Failed to rename category', 'error');
    }
}

// Delete category
// Export classified BibTeX
async function exportCategoryBibtex(categoryId) {
    try {
        showMessage('Exporting BibTeX...', 'info', 2000);

        const response = await fetch(`/api/categories/${categoryId}/export-bibtex`, {
            method: 'GET'
        });

        if (!response.ok) {
            const error = await response.json();
            showMessage(`Export failed: ${error.error}`, 'error');
            return;
        }

        // Get file name（from Content-Disposition header or use the default name）
        const contentDisposition = response.headers.get('Content-Disposition');
        let filename = 'export.bib';
        if (contentDisposition) {
            const filenameMatch = contentDisposition.match(/filename="?(.+)"?/);
            if (filenameMatch) {
                filename = filenameMatch[1];
            }
        }

        // Get file content
        const blob = await response.blob();

        // Create download link
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();

        // clean up
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

        showMessage('BibTeX Export successful', 'success');
    } catch (error) {
        console.error('Export BibTeX fail:', error);
        showMessage('Export failed, please try again later', 'error');
    }
}

async function copyCategoryArxivUrls(categoryId) {
    try {
        showMessage('Getting arXiv URL...', 'info', 2000);

        const response = await fetch(`/api/categories/${categoryId}/copy-arxiv-urls`, {
            method: 'GET'
        });

        const result = await response.json();

        if (!response.ok || !result.success) {
            showMessage(`Failed to obtain: ${result.error || 'unknown error'}`, 'error');
            return;
        }

        // copy to clipboard
        const text = result.text;
        if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(text);
            showMessage(`Copied ${result.count} indivual arXiv URL to clipboard`, 'success');
        } else {
            // Downgrade scenario: Use traditional replication methods
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            try {
                document.execCommand('copy');
                showMessage(`Copied ${result.count} indivual arXiv URL to clipboard`, 'success');
            } catch (err) {
                showMessage('Copy failed, please copy manually', 'error');
                console.error('Copy failed:', err);
            }
            document.body.removeChild(textarea);
        }
    } catch (error) {
        console.error('copy arXiv URL fail:', error);
        showMessage('Copy failed, please try again later', 'error');
    }
}

async function deleteCategory(categoryId) {
    try {
        const response = await fetch(`/api/categories/${categoryId}`, {
            method: 'DELETE'
        });

        const result = await response.json();

        if (result.success) {
            // If the currently selected category is deleted, the to-be-read list will be displayed.
            if (currentCategoryId === categoryId) {
                currentCategoryId = null;
                showReadingList();
                clearPaperInfo();
            }

            // Update local data instead of reloading the entire tree
            await updateCategoriesData();
            // Keep expanded and selected
            await renderCategoryTreeWithState();
        } else {
            showMessage(`Delete failed: ${result.error}`, 'error');
        }
    } catch (error) {
        console.error('Failed to delete category:', error);
        showMessage('Failed to delete category', 'error');
    }
}

// Set right-click menu
function setupContextMenu() {
    document.getElementById('rename-category').addEventListener('click', () => {
        const categoryId = contextMenu.dataset.categoryId;
        showRenameCategoryModal(categoryId);
        contextMenu.style.display = 'none';
    });

    document.getElementById('add-subcategory').addEventListener('click', () => {
        const categoryId = contextMenu.dataset.categoryId;
        startInlineAddCategory(categoryId);
        contextMenu.style.display = 'none';
    });

    // Pin to top/Unpin
    document.getElementById('toggle-pin-category').addEventListener('click', () => {
        const categoryId = contextMenu.dataset.categoryId;
        togglePinCategory(categoryId);
        contextMenu.style.display = 'none';
    });

    // Color selection
    document.querySelectorAll('.color-submenu .color-option').forEach(option => {
        option.addEventListener('click', (e) => {
            e.stopPropagation();
            const categoryId = contextMenu.dataset.categoryId;
            const color = option.dataset.color;
            changeCategoryColor(categoryId, color);
            contextMenu.style.display = 'none';
        });
    });

    document.getElementById('export-bibtex').addEventListener('click', () => {
        const categoryId = contextMenu.dataset.categoryId;
        exportCategoryBibtex(categoryId);
        contextMenu.style.display = 'none';
    });

    document.getElementById('copy-arxiv-urls').addEventListener('click', () => {
        const categoryId = contextMenu.dataset.categoryId;
        copyCategoryArxivUrls(categoryId);
        contextMenu.style.display = 'none';
    });

    document.getElementById('delete-category').addEventListener('click', () => {
        const categoryId = contextMenu.dataset.categoryId;
        const category = findCategoryById(categories, categoryId);
        const categoryName = category ? category.name : 'Unknown classification';

        if (confirm(`Confirm to delete category"${categoryName}"?\n\nNOTE: This will delete this category and all its subcategories, as well as allPDFdocument. This operation cannot be undone!`)) {
            deleteCategory(categoryId);
        }
        contextMenu.style.display = 'none';
    });
}

// Intelligently position the right-click menu to ensure the menu is fully visible
function positionContextMenu(menuElement, pageX, pageY) {
    // Show menu first to get its dimensions
    menuElement.style.display = 'block';
    menuElement.style.visibility = 'hidden'; // Temporarily hidden to calculate dimensions
    menuElement.style.left = '0px';
    menuElement.style.top = '0px';

    const menuRect = menuElement.getBoundingClientRect();
    const menuWidth = menuRect.width;
    const menuHeight = menuRect.height;

    // Get viewport size
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    // Calculate initial position（Relative to viewport）
    let left = pageX;
    let top = pageY;

    // Check the right border: if the menu would exceed the right border, offset it to the left
    if (left + menuWidth > viewportWidth) {
        left = viewportWidth - menuWidth - 10; // Keep10pxmargin
        // Make sure not to exceed the left margin
        if (left < 10) {
            left = 10;
        }
    }

    // Check the lower bound: if the menu will exceed the lower bound, offset it upwards
    if (top + menuHeight > viewportHeight) {
        top = viewportHeight - menuHeight - 10; // Keep10pxmargin
        // Ensure that the upper boundary is not exceeded
        if (top < 10) {
            top = 10;
        }
    }

    // Check the left margin: if the menu would exceed the left margin, offset it to the right
    if (left < 10) {
        left = 10;
    }

    // Check the upper bound: if the menu will exceed the upper bound, offset it downwards
    if (top < 10) {
        top = 10;
    }

    // Position after applying calculation
    menuElement.style.left = left + 'px';
    menuElement.style.top = top + 'px';
    menuElement.style.visibility = 'visible'; // Show menu
}

// Show right-click menu
function showContextMenu(e, categoryId) {
    contextMenu.dataset.categoryId = categoryId;

    // Update pinned button text
    const category = findCategoryById(categories, categoryId);
    const pinText = document.getElementById('pin-text');
    if (pinText && category) {
        pinText.textContent = category.pinned ? 'Unpin' : 'Pin to top';
        // update icon
        const pinIcon = document.querySelector('#toggle-pin-category i');
        if (pinIcon) {
            pinIcon.className = category.pinned ? 'fas fa-thumbtack' : 'far fa-thumbtack';
            pinIcon.style.color = category.pinned ? '#ffc107' : '#666';
        }
    }

    // Update selected state in color selection
    const currentColor = category?.iconColor || '#7d4a9d';
    document.querySelectorAll('.color-submenu .color-option').forEach(option => {
        option.classList.toggle('selected', option.dataset.color === currentColor);
    });

    // Use smart positioning
    positionContextMenu(contextMenu, e.pageX, e.pageY);
}

// Switch directory to top status
async function togglePinCategory(categoryId) {
    const category = findCategoryById(categories, categoryId);
    if (!category) return;

    const newPinned = !category.pinned;
    const originalPinned = category.pinned;

    // Update nowUI（Optimistic update）
    const categoryElement = document.querySelector(`[data-category-id="${categoryId}"]`);
    if (categoryElement) {
        // renewpinnedkind
        if (newPinned) {
            categoryElement.classList.add('pinned');
        } else {
            categoryElement.classList.remove('pinned');
        }

        // Update pin icon
        let pinIcon = categoryElement.querySelector('.pin-icon');
        if (newPinned) {
            if (!pinIcon) {
                // If there is no icon yet, add one
                const categoryName = categoryElement.querySelector('.category-name');
                if (categoryName) {
                    pinIcon = document.createElement('i');
                    pinIcon.className = 'fas fa-thumbtack pin-icon';
                    categoryName.insertAdjacentElement('afterend', pinIcon);
                }
            } else {
                pinIcon.className = 'fas fa-thumbtack pin-icon';
            }
        } else {
            if (pinIcon) {
                pinIcon.remove();
            }
        }

        // Reorder（Move pinned to front）
        const container = categoryElement.closest('.category-container');
        if (container) {
            const parent = container.parentElement;
            if (parent && (parent.classList.contains('category-children') || parent.id === 'category-tree')) {
                // Get all sibling containers（Exclude current container）
                const siblings = Array.from(parent.children).filter(child =>
                    child.classList.contains('category-container') && child !== container
                );

                if (newPinned) {
                    // Pinned: Find the first non-pinned container and insert it in front of it
                    let insertBefore = null;
                    for (const sibling of siblings) {
                        const siblingItem = sibling.querySelector('.category-item');
                        if (siblingItem && !siblingItem.classList.contains('pinned')) {
                            insertBefore = sibling;
                            break;
                        }
                    }
                    // Insert into correct position
                    if (insertBefore) {
                        parent.insertBefore(container, insertBefore);
                    } else {
                        // If there is nothing that is not pinned to the top, insert it to the front
                        const firstContainer = siblings.find(s => {
                            const item = s.querySelector('.category-item');
                            return item && item.classList.contains('pinned');
                        });
                        if (firstContainer) {
                            parent.insertBefore(container, firstContainer);
                        } else {
                            parent.insertBefore(container, parent.firstChild);
                        }
                    }
                } else {
                    // Unpin: Find the last pinned container and insert it behind it
                    let insertAfter = null;
                    for (let i = siblings.length - 1; i >= 0; i--) {
                        const siblingItem = siblings[i].querySelector('.category-item');
                        if (siblingItem && siblingItem.classList.contains('pinned')) {
                            insertAfter = siblings[i];
                            break;
                        }
                    }
                    // Insert into correct position
                    if (insertAfter) {
                        parent.insertBefore(container, insertAfter.nextSibling);
                    } else {
                        // If there is no pinned one, insert it into the first position that is not pinned.
                        let insertBefore = null;
                        for (const sibling of siblings) {
                            const siblingItem = sibling.querySelector('.category-item');
                            if (siblingItem && !siblingItem.classList.contains('pinned')) {
                                insertBefore = sibling;
                                break;
                            }
                        }
                        if (insertBefore) {
                            parent.insertBefore(container, insertBefore);
                        } else {
                            parent.appendChild(container);
                        }
                    }
                }
            }
        }
    }

    // Update local data
    category.pinned = newPinned;

    // Update button status in right-click menu（If the menu is showing）
    const contextMenu = document.getElementById('context-menu');
    if (contextMenu && contextMenu.dataset.categoryId === categoryId) {
        const pinText = document.getElementById('pin-text');
        if (pinText) {
            pinText.textContent = newPinned ? 'Unpin' : 'Pin to top';
        }
        const pinIcon = document.querySelector('#toggle-pin-category i');
        if (pinIcon) {
            pinIcon.className = newPinned ? 'fas fa-thumbtack' : 'far fa-thumbtack';
            pinIcon.style.color = newPinned ? '#ffc107' : '#666';
        }
    }

    // Show success message
    showMessage(newPinned ? 'Pinned' : 'Unpinned', 'success');

    // Asynchronously save to server（Not blockingUI）
    fetch(`/api/categories/${categoryId}/pin`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pinned: newPinned })
    })
        .then(response => response.json())
        .then(result => {
            if (!result.success) {
                // If failed, restore the original state
                category.pinned = originalPinned;
                // Re-render to restore state
                renderCategoryTreeWithState();
                showMessage('Operation failed', 'error');
            }
        })
        .catch(e => {
            console.error('Pin operation failed:', e);
            // If failed, restore the original state
            category.pinned = originalPinned;
            // Re-render to restore state
            renderCategoryTreeWithState();
            showMessage('Operation failed', 'error');
        });
}

// Change directory icon color
async function changeCategoryColor(categoryId, color) {
    const category = findCategoryById(categories, categoryId);
    if (!category) return;

    // Save original color（Used for recovery in case of failure）
    const isOthers = category.name === 'Others';
    const originalColor = category.iconColor || (isOthers ? '#8b949e' : '#7d4a9d');

    // Update nowUI（Optimistic update）
    const categoryElement = document.querySelector(`[data-category-id="${categoryId}"]`);
    if (categoryElement) {
        const folderIcon = categoryElement.querySelector('.fa-folder');
        if (folderIcon) {
            folderIcon.style.color = color;
        }
    }

    // Update local data
    category.iconColor = color;

    // Asynchronous update server（Not blockingUI）
    fetch(`/api/categories/${categoryId}/color`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ color: color })
    })
        .then(response => response.json())
        .then(result => {
            if (!result.success) {
                // If failed, restore original color
                if (categoryElement) {
                    const folderIcon = categoryElement.querySelector('.fa-folder');
                    if (folderIcon) {
                        folderIcon.style.color = originalColor;
                    }
                }
                category.iconColor = originalColor;
                showMessage('Update failed', 'error');
            }
        })
        .catch(e => {
            console.error('Update color failed:', e);
            // If failed, restore original color
            if (categoryElement) {
                const folderIcon = categoryElement.querySelector('.fa-folder');
                if (folderIcon) {
                    folderIcon.style.color = originalColor;
                }
            }
            category.iconColor = originalColor;
            showMessage('Update failed', 'error');
        });
}

// Set the paper right-click menu
function setupPaperContextMenu() {
    document.getElementById('paper-refresh-metadata').addEventListener('click', () => {
        const paperId = paperContextMenu.dataset.paperId;
        refreshPaperMetadata(paperId);
        paperContextMenu.style.display = 'none';
    });

    document.getElementById('paper-translate').addEventListener('click', () => {
        const paperId = paperContextMenu.dataset.paperId;
        requestTranslation(paperId);
        paperContextMenu.style.display = 'none';
    });

    document.getElementById('paper-analyze').addEventListener('click', () => {
        const paperId = paperContextMenu.dataset.paperId;
        requestAnalysis(paperId);
        paperContextMenu.style.display = 'none';
    });

    document.getElementById('paper-delete').addEventListener('click', () => {
        const paperId = paperContextMenu.dataset.paperId;
        deletePaper(paperId);
        paperContextMenu.style.display = 'none';
    });
}

// Show paper right-click menu
function showPaperContextMenu(e, paperId) {
    paperContextMenu.dataset.paperId = paperId;
    // Use smart positioning
    positionContextMenu(paperContextMenu, e.pageX, e.pageY);
}

// Find categories
function findCategoryById(node, id) {
    if (node.id === id) {
        return node;
    }

    if (node.children) {
        for (let child of node.children) {
            const result = findCategoryById(child, id);
            if (result) return result;
        }
    }

    return null;
}

// show loading status
function showLoading(show) {
    loading.style.display = show ? 'flex' : 'none';
}

// show message（Support custom duration）
function showMessage(message, type = 'info', duration = 3000) {
    // Create message element
    const messageDiv = document.createElement('div');
    messageDiv.className = `message message-${type}`;
    messageDiv.textContent = message;

    // Add style
    messageDiv.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 12px 20px;
        border-radius: 4px;
        color: white;
        font-size: 14px;
        z-index: 3000;
        max-width: 300px;
        word-wrap: break-word;
        animation: slideIn 0.3s ease-out;
    `;

    // Set color based on type
    const colors = {
        success: '#28a745',
        error: '#dc3545',
        warning: '#ffc107',
        info: '#17a2b8'
    };

    messageDiv.style.backgroundColor = colors[type] || colors.info;

    // add to page
    document.body.appendChild(messageDiv);

    // Automatically remove after specified time
    setTimeout(() => {
        messageDiv.style.animation = 'slideOut 0.3s ease-out';
        setTimeout(() => {
            if (messageDiv.parentNode) {
                messageDiv.parentNode.removeChild(messageDiv);
            }
        }, 300);
    }, duration);
}

// Set up paper drag and drop function
function setupPaperDrag(paperElement, paper) {
    paperElement.draggable = true;

    paperElement.addEventListener('dragstart', (e) => {
        console.log('Start dragging papers:', paper.title || paper.filename);
        draggedPaper = paper;

        // delayed additiondraggingclass to avoid affecting the drag image
        setTimeout(() => {
            paperElement.classList.add('dragging');
        }, 0);

        // Set drag data
        e.dataTransfer.setData('text/plain', paper.id);
        e.dataTransfer.effectAllowed = 'move';

        // Create custom drag images（Translucent essay strip）
        const dragImage = paperElement.cloneNode(true);
        dragImage.style.position = 'absolute';
        dragImage.style.top = '-9999px';
        dragImage.style.left = '-9999px';
        dragImage.style.width = paperElement.offsetWidth + 'px';
        dragImage.style.opacity = '0.7';
        dragImage.style.background = 'white';
        dragImage.style.border = '2px solid #007bff';
        dragImage.style.borderRadius = '4px';
        dragImage.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.2)';
        dragImage.style.padding = '6px 10px';
        dragImage.style.pointerEvents = 'none';
        document.body.appendChild(dragImage);

        // Calculate mouse position relative to element（Start from the upper left corner）
        const rect = paperElement.getBoundingClientRect();
        const offsetX = e.clientX - rect.left;
        const offsetY = e.clientY - rect.top;

        // Use the cloned element as the drag image, and the offset is the mouse click position
        e.dataTransfer.setDragImage(dragImage, offsetX, offsetY);

        // Remove the cloned element after dragging
        setTimeout(() => {
            if (document.body.contains(dragImage)) {
                document.body.removeChild(dragImage);
            }
        }, 0);
    });

    paperElement.addEventListener('dragend', (e) => {
        console.log('end drag thesis');
        paperElement.classList.remove('dragging');
        draggedPaper = null;

        // Clear all drag and drop status
        document.querySelectorAll('.category-item.drag-over, .category-item.drag-target').forEach(el => {
            el.classList.remove('drag-over', 'drag-target');
        });

        // Cleanup timer
        if (dragExpandTimer) {
            clearTimeout(dragExpandTimer);
            dragExpandTimer = null;
        }
    });
}

// Set directory drag and drop function（Make directories draggable）- Support batch drag and drop
function setupCategoryDrag(categoryElement, category) {
    // Do not allow dragging of root directory
    if (category.id === 'root') return;

    categoryElement.draggable = true;

    categoryElement.addEventListener('dragstart', (e) => {
        // If the paper is being dragged, it will not be processed.
        if (draggedPaper) {
            e.preventDefault();
            return;
        }

        // Check if in multi-select mode
        if (isCategoryMultiSelectMode && selectedCategoryIds.size > 0) {
            // Batch drag and drop: drag and drop all selected directories
            draggedCategories = [];
            selectedCategoryIds.forEach(catId => {
                const cat = findCategoryById(categories, catId);
                if (cat && cat.id !== 'root') {
                    draggedCategories.push(cat);
                }
            });

            if (draggedCategories.length === 0) {
                e.preventDefault();
                return;
            }

            console.log(`Start batch dragging ${draggedCategories.length} directories`);
            draggedCategory = null; // Clear a single drag

            // Add for all selected directories dragging style
            selectedCategoryIds.forEach(catId => {
                const el = document.querySelector(`[data-category-id="${catId}"]`);
                if (el) {
                    setTimeout(() => el.classList.add('dragging'), 0);
                }
            });
        } else {
            // single drag
            console.log('Start dragging directories:', category.name);
            draggedCategory = category;
            draggedCategories = []; // Clear batch drag and drop

            // delayed addition dragging kind
            setTimeout(() => {
                categoryElement.classList.add('dragging');
            }, 0);
        }

        // Prevent events from bubbling up and triggering dragging of parent elements
        e.stopPropagation();

        // Set drag data
        const categoryIds = draggedCategories.length > 0
            ? draggedCategories.map(c => c.id).join(',')
            : category.id;
        e.dataTransfer.setData('text/plain', `category:${categoryIds}`);
        e.dataTransfer.effectAllowed = 'move';

        // Create custom drag images
        const dragImage = document.createElement('div');
        dragImage.style.position = 'absolute';
        dragImage.style.top = '-9999px';
        dragImage.style.left = '-9999px';
        dragImage.style.padding = '8px 12px';
        dragImage.style.background = '#f8f9fa';
        dragImage.style.border = '2px solid #7d4a9d';
        dragImage.style.borderRadius = '6px';
        dragImage.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.2)';
        dragImage.style.fontSize = '13px';
        dragImage.style.fontWeight = '500';
        dragImage.style.color = '#333';
        dragImage.style.display = 'flex';
        dragImage.style.alignItems = 'center';
        dragImage.style.gap = '6px';

        if (draggedCategories.length > 0) {
            dragImage.innerHTML = `<i class="fas fa-folder" style="color: #7d4a9d;"></i> ${draggedCategories.length} directories`;
        } else {
            dragImage.innerHTML = `<i class="fas fa-folder" style="color: #7d4a9d;"></i> ${category.name}`;
        }

        document.body.appendChild(dragImage);

        const rect = categoryElement.getBoundingClientRect();
        const offsetX = e.clientX - rect.left;
        const offsetY = e.clientY - rect.top;

        e.dataTransfer.setDragImage(dragImage, offsetX, offsetY);

        setTimeout(() => {
            if (document.body.contains(dragImage)) {
                document.body.removeChild(dragImage);
            }
        }, 0);
    });

    categoryElement.addEventListener('dragend', (e) => {
        console.log('End dragging directory');
        categoryElement.classList.remove('dragging');

        // Clear all drag and drop status
        document.querySelectorAll('.category-item.dragging, .category-item.drag-over, .category-item.drag-target').forEach(el => {
            el.classList.remove('dragging', 'drag-over', 'drag-target');
        });

        // Clear the drag style of the root directory
        categoryTree.classList.remove('drag-over-root');

        // Clear drag and drop data
        draggedCategory = null;
        draggedCategories = [];

        // Cleanup timer
        if (dragExpandTimer) {
            clearTimeout(dragExpandTimer);
            dragExpandTimer = null;
        }
    });
}

// Set category drag target function（Receive drag and drop of paper or table of contents）
function setupCategoryDropTarget(categoryElement, category) {
    const container = categoryElement.closest('.category-container');

    function onDragOver(e) {
        // mustpreventDefaultOnly alloweddrop
        e.preventDefault();
        e.stopPropagation();

        // Check if there is a dragged paper or table of contents（Single or batch）
        if (!draggedPaper && !draggedCategory && draggedCategories.length === 0) {
            return;
        }

        // If you drag and drop a directory（Single or batch）, cannot be dragged to itself or its own subdirectory
        const categoriesToCheck = draggedCategories.length > 0 ? draggedCategories : (draggedCategory ? [draggedCategory] : []);

        for (const draggedCat of categoriesToCheck) {
            if (draggedCat.id === category.id) {
                e.dataTransfer.dropEffect = 'none';
                return;
            }
            // Check if it is a subdirectory（Simple check: whether the target is dragging the element DOM in subtree）
            const draggedElement = document.querySelector(`[data-category-id="${draggedCat.id}"]`);
            if (draggedElement) {
                const draggedContainer = draggedElement.closest('.category-container');
                if (draggedContainer && draggedContainer.contains(categoryElement)) {
                    e.dataTransfer.dropEffect = 'none';
                    return;
                }
            }
        }

        e.dataTransfer.dropEffect = 'move';

        // Clear the drag style of the root directory（if exists）
        categoryTree.classList.remove('drag-over-root');

        // Add drag-and-hover style
        categoryElement.classList.add('drag-over');

        // If there are subcategories and they are not expanded, set automatic expansion.
        if (container) {
            const children = container.querySelector('.category-children');
            const toggle = categoryElement.querySelector('.category-toggle');

            if (children && children.classList.contains('collapsed') && toggle) {
                // Clear previous timer
                if (dragExpandTimer) {
                    clearTimeout(dragExpandTimer);
                }

                // Set new expansion timer
                dragExpandTimer = setTimeout(() => {
                    console.log('Automatically expand categories:', category.name);
                    toggle.classList.add('expanded');
                    children.classList.remove('collapsed');
                    expandedCategories.add(category.id);
                }, 800); // 800ms automatically expand after
            }
        }
    }

    categoryElement.addEventListener('dragenter', (e) => {
        e.preventDefault();
        e.stopPropagation();
        onDragOver(e);
    });

    categoryElement.addEventListener('dragover', onDragOver);

    categoryElement.addEventListener('dragleave', (e) => {
        if (!draggedPaper && !draggedCategory && draggedCategories.length === 0) return;

        // Check if the element is actually left（instead of going into child elements）
        const rect = categoryElement.getBoundingClientRect();
        const x = e.clientX;
        const y = e.clientY;

        if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) {
            categoryElement.classList.remove('drag-over');

            // Clear expansion timer
            if (dragExpandTimer) {
                clearTimeout(dragExpandTimer);
                dragExpandTimer = null;
            }
        }
    });

    categoryElement.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();

        categoryElement.classList.remove('drag-over');
        categoryElement.classList.add('drag-target');

        // Clear the drag style of the root directory
        categoryTree.classList.remove('drag-over-root');

        // clear timer
        if (dragExpandTimer) {
            clearTimeout(dragExpandTimer);
            dragExpandTimer = null;
        }

        // Handle paper drag and drop
        if (draggedPaper) {
            console.log('Place article into category:', category.name, 'paper:', draggedPaper.title || draggedPaper.filename);
            movePaper(draggedPaper.id, category.id);
        }
        // Handle directory drag and drop（Batch or single）
        else if (draggedCategories.length > 0) {
            console.log(`Batch placement ${draggedCategories.length} directories to categories:`, category.name);
            moveCategories(draggedCategories.map(c => c.id), category.id);
        }
        else if (draggedCategory) {
            console.log('Place directory into categories:', category.name, 'Table of contents:', draggedCategory.name);
            moveCategory(draggedCategory.id, category.id);
        }
        else {
            console.log('dropThere is no dragged paper or table of contents');
        }

        // Displays target status briefly and then clears
        setTimeout(() => {
            categoryElement.classList.remove('drag-target');
        }, 1000);
    });
}

// Move article to new category
async function movePaper(paperId, targetCategoryId) {
    try {
        const response = await fetch(`/api/paper/${paperId}/move`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                target_category_id: targetCategoryId
            })
        });

        const result = await response.json();

        if (result.success) {
            // Moved successfully, no prompt is displayed
            console.log('Paper moved successfully');

            // Update local data
            await updateCategoriesData();
            await renderCategoryTreeWithState();

            // If the source category is currently displayed, reload the paper list
            if (currentCategoryId === result.source_category || currentCategoryId === result.target_category) {
                loadPapers(currentCategoryId);
            }
        } else {
            showMessage(`Move failed: ${result.error}`, 'error');
        }
    } catch (error) {
        console.error('Failed to move paper:', error);
        showMessage('Failed to move paper', 'error');
    }
}

// Move directory to new parent directory
async function moveCategory(categoryId, targetParentId) {
    try {
        const response = await fetch(`/api/categories/${categoryId}/move`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                target_parent_id: targetParentId
            })
        });

        const result = await response.json();

        if (result.success) {
            console.log('Directory moved successfully:', result.old_path, '->', result.new_path);
            showMessage('Directory moved successfully', 'success');

            // Update local data and re-render the classification tree
            await updateCategoriesData();
            await renderCategoryTreeWithState();

            // If the currently selected category is moved, update the selected status
            if (currentCategoryId === categoryId) {
                // Re-select this category
                const categoryItem = document.querySelector(`.category-item[data-category-id="${categoryId}"]`);
                if (categoryItem) {
                    categoryItem.classList.add('selected');
                }
            }
        } else {
            showMessage(`Move failed: ${result.error}`, 'error');
        }
    } catch (error) {
        console.error('Failed to move directory:', error);
        showMessage('Failed to move directory', 'error');
    }
}

// Batch move multiple directories to new parent directories
async function moveCategories(categoryIds, targetParentId) {
    if (!categoryIds || categoryIds.length === 0) return;

    let successCount = 0;
    let failCount = 0;
    const errors = [];

    // Move directories one by one
    for (const categoryId of categoryIds) {
        try {
            const response = await fetch(`/api/categories/${categoryId}/move`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    target_parent_id: targetParentId
                })
            });

            const result = await response.json();

            if (result.success) {
                successCount++;
                console.log(`Directory moved successfully: ${categoryId}`);
            } else {
                failCount++;
                errors.push(result.error || 'unknown error');
            }
        } catch (error) {
            failCount++;
            errors.push(error.message || 'network error');
            console.error(`Failed to move directory ${categoryId}:`, error);
        }
    }

    // Show results
    if (successCount > 0) {
        if (failCount === 0) {
            showMessage(`Moved successfully ${successCount} directories`, 'success');
        } else {
            showMessage(`Moved successfully ${successCount} directory, failed ${failCount} indivual`, 'warning');
        }
    } else {
        showMessage(`Move failed: ${errors[0] || 'unknown error'}`, 'error');
    }

    // Update local data and re-render the classification tree
    if (successCount > 0) {
        await updateCategoriesData();
        await renderCategoryTreeWithState();
    }

    // Regardless of success or failure, exit multi-select mode（Because the operation has been completed）
    if (isCategoryMultiSelectMode) {
        exitCategoryMultiSelectMode();
    }
}

// Open Chinese versionPDF
function openChineseVersion(paperId) {
    const paper = papers.find(p => p.id === paperId);
    if (!paper || !paper.has_chinese_version) {
        showMessage('Chinese version does not exist', 'error');
        return;
    }
    const viewerUrl = `/viewer/${paperId}?chinese=true`;
    window.open(viewerUrl, '_blank');
    markPaperViewed(paperId);
}

// Open PDF reader（Open the original version）
function openPDFViewer(paperId) {
    console.log('Open PDF reader:', paperId);
    const viewerUrl = `/viewer/${paperId}`;
    window.open(viewerUrl, '_blank');
    markPaperViewed(paperId);
}

// show arXiv Upload modal box
function showArxivUploadModal() {
    const modalTitle = document.querySelector('#modal-title');
    const modalBody = document.querySelector('#modal-body');
    const confirmBtn = document.querySelector('#modal-confirm');
    const cancelBtn = document.querySelector('#modal-cancel');

    modalTitle.textContent = 'Import paper from arXiv';
    modalBody.innerHTML = `
        <div style="margin-bottom: 15px;">
            <label for="arxiv-url" style="display: block; margin-bottom: 5px; font-weight: 500;">arXiv URL or ID:</label>
            <input type="text" id="arxiv-url" placeholder="For example: https://arxiv.org/pdf/2511.03725 or 2511.03725" 
                   style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 4px; font-size: 14px;">
            <p style="margin-top: 5px; font-size: 12px; color: #666;">
                Supported formats:https://arxiv.org/pdf/2511.03725、https://arxiv.org/abs/2511.03725 Or enter directly arXiv ID
            </p>
        </div>
        <div id="arxiv-upload-status" style="display: none; margin-top: 10px;">
            <div class="loading-small" style="display: flex; align-items: center; gap: 10px;">
                <div class="spinner-small"></div>
                <span>Downloading and importing...</span>
            </div>
        </div>
    `;

    confirmBtn.style.display = 'inline-block';
    confirmBtn.textContent = 'import';
    cancelBtn.textContent = 'Cancel';

    // Clear all previous event listeners（by removing and re-adding）
    const confirmBtnClone = confirmBtn.cloneNode(true);
    const cancelBtnClone = cancelBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(confirmBtnClone, confirmBtn);
    cancelBtn.parentNode.replaceChild(cancelBtnClone, cancelBtn);

    // Retrieve button reference
    const newConfirmBtn = document.getElementById('modal-confirm');
    const newCancelBtn = document.getElementById('modal-cancel');

    newConfirmBtn.onclick = async (e) => {
        e.preventDefault();
        e.stopPropagation();

        const arxivUrl = document.getElementById('arxiv-url').value.trim();
        if (!arxivUrl) {
            showMessage('Please enter arXiv URL or ID', 'warning');
            return;
        }
        // Non-blocking import: close the pop-up window immediately and import in the background
        hideModal();
        showMessage('Start background import…', 'success');

        // Background download and refresh category count when complete/Current list
        (async () => {
            try {
                // If you are in the to-read list interface, use the temporary directory；Otherwise use the current category
                const isInReadingList = currentViewMode === 'reading-list';
                const requestBody = {
                    arxiv_url: arxivUrl,
                };

                if (isInReadingList) {
                    requestBody.use_temp_dir = true;
                } else {
                    requestBody.category_id = currentCategoryId;
                }

                const response = await fetch('/api/upload/arxiv', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(requestBody)
                });
                const result = await response.json();
                if (response.ok && result.success) {
                    showMessage('Paper imported successfully', 'success');
                    // First update the to-be-read list count andIDCollection to ensure status synchronization
                    await updateReadingListCount();
                    if (isInReadingList) {
                        // If you are in the to-read list interface, refresh the to-read list
                        await showReadingList();
                    } else if (currentCategoryId) {
                        loadPapers(currentCategoryId);
                    }
                    await updateCategoriesData();
                    renderCategoryTreeWithState();
                } else {
                    showMessage(result.error || 'Import failed', 'error');
                }
            } catch (err) {
                console.error('import arXiv Thesis failed:', err);
                showMessage('Import failed, please try again later', 'error');
            }
        })();
    };

    // Set cancel button - direct coverage onclick
    newCancelBtn.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        hideModal();
    };

    // Support enter key submission
    const arxivUrlInput = document.getElementById('arxiv-url');
    if (arxivUrlInput) {
        arxivUrlInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                newConfirmBtn.click();
            }
        });

        // Auto focus input box
        setTimeout(() => {
            arxivUrlInput.focus();
        }, 100);
    }

    showModal();
}

// global search（real time）
function setupGlobalSearch() {
    const input = document.getElementById('global-search');
    const panel = document.getElementById('search-results');
    if (!input || !panel) return;

    let timer = null;
    input.addEventListener('input', () => {
        const q = input.value.trim();
        clearTimeout(timer);
        if (!q) { panel.style.display = 'none'; panel.innerHTML = ''; return; }
        timer = setTimeout(async () => {
            try {
                const params = new URLSearchParams();
                params.set('q', q);
                // Default full database search: no longer automatically included category_id
                const resp = await fetch(`/api/search?${params.toString()}`);
                const data = await resp.json();
                renderSearchResults(panel, q, data.results || []);
            } catch (e) {
                console.error('Search failed', e);
            }
        }, 250);
    });

    document.addEventListener('click', (e) => {
        if (!panel.contains(e.target) && e.target !== input) {
            panel.style.display = 'none';
        }
    });
}

function renderSearchResults(panel, q, results) {
    if (!results.length) { panel.style.display = 'none'; panel.innerHTML = ''; return; }
    const esc = (s) => (s || '').replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
    const hi = (text) => esc(text).replace(new RegExp(`(${escapeRegExp(q)})`, 'ig'), '<mark>$1</mark>');
    panel.innerHTML = results.map(r => {
        const fields = (r.matched_fields || []).map(f => `<span class="search-field-tag">${f}</span>`).join('');
        const authors = r.authors ? `<div class="search-meta">${hi(r.authors)}</div>` : '';
        // Prioritize context snippets for matching fields（notes first, then abstract）
        // If there are no matching fragments, display the summary before200character
        let abs = '';
        if (r.notes_snippet) {
            // If the match is notes,show notes context fragment
            abs = `<div class="search-meta"><strong>Remark:</strong> ${hi(r.notes_snippet)}</div>`;
        } else if (r.abstract_snippet) {
            // If the match is abstract,show abstract context fragment
            abs = `<div class="search-meta">${hi(r.abstract_snippet)}</div>`;
        } else if (r.abstract) {
            // If there is no context fragment, display the summary before200character
            abs = `<div class="search-meta">${hi(r.abstract.slice(0, 200))}...</div>`;
        }
        // Add to category_id Attribute, used to switch categories when clicked
        const categoryId = r.category_id || '';
        return `<div class="search-item" data-paper-id="${r.id}" data-category-id="${categoryId}">
            <div class="search-title">${hi(r.title || r.filename || '')} ${fields}</div>
            ${authors}
            ${abs}
        </div>`;
    }).join('');
    panel.style.display = 'block';
    panel.querySelectorAll('.search-item').forEach(item => {
        item.addEventListener('click', async () => {
            const pid = item.getAttribute('data-paper-id');
            const categoryId = item.getAttribute('data-category-id');

            // Hide search results panel
            panel.style.display = 'none';

            // Optimization: first check whether the paper is already in the current list
            const existingPaperItem = document.querySelector(`.paper-item[data-paper-id="${pid}"]`);
            if (existingPaperItem && currentCategoryId === categoryId) {
                // The paper is already in the current category, directly select and scroll
                selectPaper(pid);
                setTimeout(() => {
                    existingPaperItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }, 50);
                return;
            }

            // If the paper has classification information, switch to that classification first
            if (categoryId && categoryId !== 'null' && categoryId !== 'undefined') {
                try {
                    // Get the paper information first for quick display
                    const paperResponse = await fetch(`/api/paper/${pid}`);
                    let targetPaper = null;
                    if (paperResponse.ok) {
                        targetPaper = await paperResponse.json();
                    }

                    // Get classified information
                    const categories = await fetch('/api/categories').then(r => r.json());
                    const category = findCategoryById(categories, categoryId);

                    if (category) {
                        // Expand the category tree to make sure the target category is visible
                        expandToCategoryPath(categoryId);

                        // Set up first currentPaperId,so renderPapersList will be automatically selected
                        currentPaperId = pid;

                        // If the target paper information has been obtained, display it first（Optimize experience）
                        if (targetPaper) {
                            // Temporarily display target papers to provide immediate feedback
                            papersList.innerHTML = `
                                <div class="paper-header">
                                    <div class="paper-header-col"></div>
                                    <div class="paper-header-col">title<div class="paper-header-resizer" data-col="1"></div></div>
                                    <div class="paper-header-col">date<div class="paper-header-resizer" data-col="2"></div></div>
                                    <div class="paper-header-col">AI translate<div class="paper-header-resizer" data-col="3"></div></div>
                                    <div class="paper-header-col">AI Interpretation<div class="paper-header-resizer" data-col="4"></div></div>
                                    <div class="paper-header-col">To be read</div>
                                </div>
                            `;
                            // Add column width adjustment function
                            setupColumnResizing();
                            const tempDiv = document.createElement('div');
                            tempDiv.className = 'paper-item selected';
                            tempDiv.dataset.paperId = targetPaper.id;
                            tempDiv.innerHTML = generatePaperItemHTML(targetPaper, true);
                            papersList.appendChild(tempDiv);
                            setupPaperDrag(tempDiv, targetPaper);
                            tempDiv.addEventListener('click', () => selectPaper(pid));
                            tempDiv.addEventListener('dblclick', (e) => {
                                if (!e.target.closest('button') && !e.target.closest('.paper-col-btn')) {
                                    e.preventDefault();
                                    openPDFViewer(pid);
                                }
                            });
                            // Select and load paper information immediately
                            selectPaper(pid);
                            loadPaperInfo(pid);
                        }

                        // Switch to this category（Load full list asynchronously）
                        selectCategory(categoryId, category.name);

                        // Wait until the paper list is loaded and then make sure it is selected.
                        // Use a smarter waiting mechanism
                        let attempts = 0;
                        const maxAttempts = 50; // most wait 5 Second（It may take longer if the paper is large）
                        const checkAndSelect = setInterval(() => {
                            attempts++;
                            const paperItem = document.querySelector(`.paper-item[data-paper-id="${pid}"]`);
                            if (paperItem) {
                                clearInterval(checkAndSelect);
                                // Make sure it is selected
                                selectPaper(pid);
                                // Scroll to thesis item
                                setTimeout(() => {
                                    paperItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
                                }, 100);
                            } else if (attempts >= maxAttempts) {
                                clearInterval(checkAndSelect);
                                // After timeout, try to select directly（Maybe the paper is already on the list）
                                selectPaper(pid);
                            }
                        }, 100);
                    } else {
                        // Cannot find the category, try to select the paper directly
                        selectPaper(pid);
                    }
                } catch (error) {
                    console.error('Failed to switch categories:', error);
                    // If it fails, try to select the paper directly.
                    selectPaper(pid);
                }
            } else {
                // There is no classification information, just try to select the paper
                selectPaper(pid);
            }
        });
    });
}

function escapeRegExp(s) {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Daily arXiv Search highlighting
function highlightDailyArxiv(text) {
    if (!text || !dailyArxivSearchQuery || !dailyArxivSearchQuery.trim()) {
        return escapeHtml(text || '');
    }
    const q = dailyArxivSearchQuery.trim();
    const escaped = escapeRegExp(q);
    const re = new RegExp(`(${escaped})`, 'ig');
    return escapeHtml(text || '').replace(re, '<mark>$1</mark>');
}

// Delete paper
// Re-crawl PDF metadata
async function refreshPaperMetadata(paperId) {
    try {
        const paper = papers.find(p => p.id === paperId);
        if (!paper) {
            showMessage('Paper not found', 'error');
            return;
        }

        showMessage('Recrawling metadata...', 'info', 2000);

        const response = await fetch(`/api/paper/${paperId}/refresh-metadata`, {
            method: 'POST'
        });

        if (response.ok) {
            const result = await response.json();
            showMessage('Metadata fetched successfully and is being updated...', 'success', 2000);

            // Start polling to detect updates
            const initialTitle = paper.title;
            startPollingPaperUpdate(paperId, currentCategoryId, initialTitle);

        } else {
            const error = await response.json();
            showMessage(`Fetch failed: ${error.error}`, 'error');
        }
    } catch (error) {
        console.error('Recrawling metadata failed:', error);
        showMessage('Fetching failed, please try again later', 'error');
    }
}

async function deletePaper(paperId, event = null) {
    if (event) {
        event.stopPropagation();
    }

    // In reading-list view, "delete" should only remove from the reading list,
    // not delete the actual paper file or remove it from its category.
    if (currentViewMode === 'reading-list') {
        await removeFromReadingList(paperId);
        return;
    }

    try {
        // Optimistic update: remove from list first
        papers = papers.filter(p => p.id !== paperId);
        renderPapersList();

        const response = await fetch(`/api/paper/${paperId}`, { method: 'DELETE' });
        if (response.ok) {
            showMessage('Paper deleted successfully', 'success');
            await updateCategoriesData();
            renderCategoryTreeWithState();
            updateReadingListCount();
        } else {
            const error = await response.json();
            showMessage(`Delete failed: ${error.error}`, 'error');
            // Rollback: Reload the list
            if (currentCategoryId) loadPapers(currentCategoryId);
        }
    } catch (error) {
        console.error('Failed to delete paper:', error);
        showMessage('Deletion failed, please try again later', 'error');
        if (currentCategoryId) loadPapers(currentCategoryId);
    }
}

// Switch like status
async function toggleStar(paperId, event) {
    event.stopPropagation();

    try {
        const paper = papers.find(p => p.id === paperId);
        if (!paper) {
            showMessage('Paper not found', 'error');
            return;
        }

        const newStarred = !paper.starred;

        const response = await fetch(`/api/paper/${paperId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                starred: newStarred
            })
        });

        if (response.ok) {
            // Update local data
            paper.starred = newStarred;

            // Re-render the paper list to update the display
            renderPapersList();

            // If this paper is currently selected, reselect it to keep it selected.
            if (currentPaperId === paperId) {
                selectPaper(paperId);
            }

            showMessage(newStarred ? 'Liked' : 'Like canceled', 'success');
        } else {
            showMessage('Operation failed', 'error');
        }
    } catch (error) {
        console.error('Failed to switch like status:', error);
        showMessage('Operation failed, please try again later', 'error');
    }
}

// Edit paper information
async function editPaper(paperId, event) {
    event.stopPropagation();

    try {
        // Get paper information
        const response = await fetch(`/api/paper/${paperId}`);
        if (!response.ok) {
            showMessage('Failed to obtain paper information', 'error');
            return;
        }

        const paper = await response.json();

        // Show edit modal box
        const modalTitle = document.querySelector('#modal-title');
        const modalBody = document.querySelector('#modal-body');
        const confirmBtn = document.querySelector('#modal-confirm');

        modalTitle.textContent = 'Edit paper information';
        modalBody.innerHTML = `
            <div class="form-group">
                <label for="paper-title">Paper title</label>
                <input type="text" id="paper-title" value="${paper.title || ''}" placeholder="Paper title">
            </div>
            <div class="form-group">
                <label for="paper-authors">author</label>
                <input type="text" id="paper-authors" value="${paper.authors || ''}" placeholder="Author name, multiple authors separated by commas">
            </div>
            <div class="form-group">
                <label for="paper-affiliation">unit/mechanism</label>
                <input type="text" id="paper-affiliation" value="${paper.affiliation || ''}" placeholder="Author's unit or institution">
            </div>
            <div class="form-group">
                <label for="paper-year">year of publication</label>
                <input type="number" id="paper-year" value="${paper.year || ''}" placeholder="year of publication" min="1900" max="2030">
            </div>
            <div class="form-group">
                <label for="paper-journal">Journal/Meeting</label>
                <input type="text" id="paper-journal" value="${paper.journal || ''}" placeholder="Journal or conference name">
            </div>
            <div class="form-group">
                <label for="paper-abstract">summary</label>
                <textarea id="paper-abstract" rows="4" placeholder="Paper abstract">${paper.abstract || ''}</textarea>
            </div>
        `;

        confirmBtn.onclick = async () => {
            const updatedPaper = {
                title: document.getElementById('paper-title').value.trim(),
                authors: document.getElementById('paper-authors').value.trim(),
                affiliation: document.getElementById('paper-affiliation').value.trim(),
                year: document.getElementById('paper-year').value.trim(),
                journal: document.getElementById('paper-journal').value.trim(),
                abstract: document.getElementById('paper-abstract').value.trim()
            };

            // Remove null values
            Object.keys(updatedPaper).forEach(key => {
                if (!updatedPaper[key]) {
                    delete updatedPaper[key];
                }
            });

            try {
                const updateResponse = await fetch(`/api/paper/${paperId}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(updatedPaper)
                });

                if (updateResponse.ok) {
                    const result = await updateResponse.json();
                    showMessage('Paper information updated successfully', 'success');
                    hideModal();

                    // If the title is modified, the background will automatically re-fetch and start polling.
                    if (result.auto_refresh_triggered && updatedPaper.title) {
                        console.log('[Automatic recapture] The title has been modified and the background is re-crawling arXiv information...');

                        // First refresh the list to display the content manually updated by the user.
                        if (currentCategoryId) {
                            await loadPapers(currentCategoryId);
                            // If this paper is currently selected, refresh the details
                            if (currentPaperId === paperId) {
                                const paperResponse = await fetch(`/api/paper/${paperId}`);
                                if (paperResponse.ok) {
                                    const updatedPaperData = await paperResponse.json();
                                    renderPaperInfo(updatedPaperData);
                                }
                            }
                        }

                        // Delay the start of polling, give the background some processing time, and pass in the updated title
                        setTimeout(() => {
                            startPollingPaperUpdate(paperId, currentCategoryId, updatedPaper.title, 15);
                        }, 2000);
                    } else {
                        // Refresh the list of papers in the current category
                        if (currentCategoryId) {
                            loadPapers(currentCategoryId);
                        }
                    }
                } else {
                    const error = await updateResponse.json();
                    showMessage(`Update failed: ${error.error}`, 'error');
                }
            } catch (error) {
                console.error('Failed to update paper information:', error);
                showMessage('Update failed, please try again later', 'error');
            }
        };

        showModal();
        document.getElementById('paper-title').focus();

    } catch (error) {
        console.error('Failed to edit paper:', error);
        showMessage('Editing failed, please try again later', 'error');
    }
}

// Open the mobile thesis directory selector
async function openMovePaperPicker(paperId, event) {
    event.stopPropagation();
    try {
        // Make sure to get the latest categories
        await updateCategoriesData();
        const modalTitle = document.querySelector('#modal-title');
        const modalBody = document.querySelector('#modal-body');
        const confirmBtn = document.querySelector('#modal-confirm');
        const cancelBtn = document.querySelector('#modal-cancel');

        modalTitle.textContent = 'Move to directory';
        modalBody.innerHTML = `
            <div class="form-group">
                <div id="move-category-tree" style="max-height:50vh; overflow:auto; padding:8px; border:1px solid #eee; border-radius:6px;"></div>
            </div>
        `;

        // Render an optional classification tree（radio）
        const treeContainer = modalBody.querySelector('#move-category-tree');
        renderCategorySelectTree(categories, treeContainer);

        confirmBtn.onclick = async () => {
            const selected = treeContainer.querySelector('input[name="target-category"]:checked');
            if (!selected) { showMessage('Please select the target directory', 'warning'); return; }
            const targetId = selected.value;
            try {
                await movePaper(paperId, targetId);
                hideModal();
            } catch (e) {
                console.error(e);
            }
        };
        showModal();
    } catch (e) {
        console.error('Failed to open mobile selector', e);
        showMessage('Failed to open mobile selector', 'error');
    }
}

function renderCategorySelectTree(root, container) {
    container.innerHTML = '';

    function createSelectableNode(node, level = 0) {
        const wrapper = document.createElement('div');
        wrapper.className = 'category-container';

        const item = document.createElement('div');
        item.className = 'category-item';
        item.dataset.categoryId = node.id || 'root';
        item.style.paddingLeft = `${level * 20 + 12}px`;

        const hasChildren = node.children && node.children.length > 0;
        const isOthers = node.name === 'Others';
        const folderColor = isOthers ? '#8b949e' : '#7d4a9d';
        item.innerHTML = `
            ${hasChildren ? '<button class="category-toggle"><i class="fas fa-chevron-right"></i></button>' : '<span style="width: 16px; margin-right: 5px;"></span>'}
            <i class="fas fa-folder" style="margin-right: 8px; color: ${folderColor};"></i>
            <span class="category-name">${node.name || 'Root'}</span>
            ${node.id ? `<input type="radio" name="target-category" value="${node.id}" style="margin-left:auto; margin-right:10px;">` : ''}
        `;

        // Expand/fold
        const toggle = item.querySelector('.category-toggle');
        let childrenDiv = null;
        if (hasChildren) {
            childrenDiv = document.createElement('div');
            childrenDiv.className = 'category-children collapsed';
        }

        if (toggle && childrenDiv) {
            toggle.addEventListener('click', (e) => {
                e.stopPropagation();
                const isCollapsed = childrenDiv.classList.contains('collapsed');
                childrenDiv.classList.toggle('collapsed');
                toggle.classList.toggle('expanded', isCollapsed);
            });
        }

        // Click on the name to also select it radio
        const label = item.querySelector('.category-name');
        const radio = item.querySelector('input[type="radio"]');
        if (radio) {
            label.addEventListener('click', (e) => {
                e.stopPropagation();
                radio.checked = true;
            });
            item.addEventListener('click', (e) => {
                // avoid clicks toggle Repeated trigger
                if (!e.target.classList.contains('category-toggle') && !e.target.closest('.category-toggle')) {
                    radio.checked = true;
                }
            });
        }

        wrapper.appendChild(item);

        if (hasChildren) {
            const sortedChildren = [...node.children].sort((a, b) => {
                if (a.pinned && !b.pinned) return -1;
                if (!a.pinned && b.pinned) return 1;
                if (a.name === 'Others') return -1;
                if (b.name === 'Others') return 1;
                return (a.name || '').localeCompare(b.name || '');
            });
            sortedChildren.forEach(child => {
                const childEl = createSelectableNode(child, level + 1);
                childrenDiv.appendChild(childEl);
            });
            wrapper.appendChild(childrenDiv);
        }

        return wrapper;
    }

    // rendering Root child nodes as optional
    if (root && root.children) {
        const sortedTop = [...root.children].sort((a, b) => {
            if (a.pinned && !b.pinned) return -1;
            if (!a.pinned && b.pinned) return 1;
            if (a.name === 'Others') return -1;
            if (b.name === 'Others') return 1;
            return (a.name || '').localeCompare(b.name || '');
        });
        sortedTop.forEach(child => container.appendChild(createSelectableNode(child, 0)));
    }
}

// Add toCSSanimation
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

// ========== Essay multiple choice logic ==========
function toggleMultiSelectMode() {
    isMultiSelectMode = !isMultiSelectMode;
    if (!isMultiSelectMode) {
        selectedPaperIds.clear();
        lastSelectedIndex = null;
    }
    updateBatchUI();
    renderPapersList();
}

function exitMultiSelectMode() {
    if (!isMultiSelectMode) return;
    isMultiSelectMode = false;
    selectedPaperIds.clear();
    lastSelectedIndex = null;
    updateBatchUI();
    renderPapersList();
}

// ========== Directory multiple selection logic ==========

// Get an ordered list of all visible directory elements
function getAllVisibleCategoryElements() {
    return Array.from(document.querySelectorAll('.category-item[data-category-id]'));
}

// Get the index of a directory in the visible list
function getCategoryIndex(categoryId) {
    const elements = getAllVisibleCategoryElements();
    return elements.findIndex(el => el.dataset.categoryId === categoryId);
}

// deal with Ctrl + Click on the directory to select
function handleCategoryMultiSelectClick(e, categoryId, element) {
    if (!isCategoryMultiSelectMode) {
        isCategoryMultiSelectMode = true;
    }

    if (selectedCategoryIds.has(categoryId)) {
        selectedCategoryIds.delete(categoryId);
        element.classList.remove('multi-selected');
    } else {
        selectedCategoryIds.add(categoryId);
        element.classList.add('multi-selected');
    }

    lastSelectedCategoryIndex = getCategoryIndex(categoryId);

    // If no directory is selected, exit multi-select mode
    if (selectedCategoryIds.size === 0) {
        exitCategoryMultiSelectMode();
    }

    updateCategoryBatchUI();
}

// deal with Shift + Click on directory range selection
function handleCategoryShiftSelect(categoryId, element) {
    const currentIndex = getCategoryIndex(categoryId);
    if (currentIndex === -1 || lastSelectedCategoryIndex === null) return;

    const elements = getAllVisibleCategoryElements();
    const start = Math.min(lastSelectedCategoryIndex, currentIndex);
    const end = Math.max(lastSelectedCategoryIndex, currentIndex);

    if (!isCategoryMultiSelectMode) {
        isCategoryMultiSelectMode = true;
    }

    // Select all directories within the range
    for (let i = start; i <= end; i++) {
        const el = elements[i];
        if (el) {
            const id = el.dataset.categoryId;
            selectedCategoryIds.add(id);
            el.classList.add('multi-selected');
        }
    }

    updateCategoryBatchUI();
}

// Exit directory multi-select mode
function exitCategoryMultiSelectMode() {
    if (!isCategoryMultiSelectMode) return;
    isCategoryMultiSelectMode = false;
    selectedCategoryIds.clear();
    lastSelectedCategoryIndex = null;

    // Remove all multiple selection styles
    document.querySelectorAll('.category-item.multi-selected').forEach(el => {
        el.classList.remove('multi-selected');
    });

    updateCategoryBatchUI();
}

// Update directory batch operation UI
function updateCategoryBatchUI() {
    // You can add the display logic of the batch operation toolbar here
    console.log(`selected ${selectedCategoryIds.size} directories`);
}

// Display the right-click menu for directory batch operations
function showCategoryBatchContextMenu(e) {
    const menu = document.createElement('div');
    menu.className = 'context-menu category-batch-menu';
    menu.style.cssText = `
        position: fixed;
        z-index: 10000;
        background: white;
        border: 1px solid #ddd;
        border-radius: 6px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        padding: 4px 0;
        min-width: 150px;
    `;

    menu.innerHTML = `
        <div class="context-menu-item" data-action="delete" style="padding: 8px 16px; cursor: pointer; display: flex; align-items: center; gap: 8px;">
            <i class="fas fa-trash" style="color: #dc3545;"></i>
            <span>Delete selected directory (${selectedCategoryIds.size})</span>
        </div>
    `;

    // Click delete
    menu.querySelector('[data-action="delete"]').addEventListener('click', () => {
        confirmDeleteSelectedCategories();
        document.body.removeChild(menu);
    });

    // mouseover effect
    menu.querySelectorAll('.context-menu-item').forEach(item => {
        item.addEventListener('mouseenter', () => item.style.background = '#f5f5f5');
        item.addEventListener('mouseleave', () => item.style.background = 'transparent');
    });

    // Click elsewhere to close the menu
    const closeMenu = (ev) => {
        if (!menu.contains(ev.target)) {
            if (document.body.contains(menu)) {
                document.body.removeChild(menu);
            }
            document.removeEventListener('click', closeMenu);
        }
    };
    setTimeout(() => document.addEventListener('click', closeMenu), 0);

    // first add to DOM, then use smart positioning
    document.body.appendChild(menu);
    // Use smart positioning（Note: Batch menu usage clientX/clientY, needs to be converted to pageX/pageY）
    const pageX = e.pageX || (e.clientX + window.scrollX);
    const pageY = e.pageY || (e.clientY + window.scrollY);
    positionContextMenu(menu, pageX, pageY);
}

// Confirm deletion of multiple selected directories
async function confirmDeleteSelectedCategories() {
    const count = selectedCategoryIds.size;
    if (count === 0) return;

    const confirmed = confirm(`Are you sure you want to delete the selected ${count} A directory?\nThis operation will delete all papers in the directory at the same time and cannot be restored!`);
    if (!confirmed) return;

    const ids = Array.from(selectedCategoryIds);
    let successCount = 0;
    let failCount = 0;

    for (const categoryId of ids) {
        try {
            const response = await fetch(`/api/categories/${categoryId}`, {
                method: 'DELETE'
            });
            const result = await response.json();
            if (result.success) {
                successCount++;
            } else {
                failCount++;
            }
        } catch (e) {
            failCount++;
        }
    }

    exitCategoryMultiSelectMode();
    await updateCategoriesData();
    await renderCategoryTreeWithState();

    if (failCount === 0) {
        showMessage(`successfully deleted ${successCount} directories`, 'success');
    } else {
        showMessage(`Deletion completed: Success ${successCount},fail ${failCount}`, 'warning');
    }
}

// Confirm deletion of a single directory
function confirmDeleteCategory(categoryId) {
    const categoryNode = findCategoryNodeLocal(categories, categoryId);
    const name = categoryNode ? categoryNode.name : 'the directory';

    const confirmed = confirm(`Confirm you want to delete the directory"${name}"?\nThis operation will delete all papers in the directory at the same time and cannot be restored!`);
    if (confirmed) {
        deleteCategory(categoryId);
    }
}

// Find directory nodes in local data
function findCategoryNodeLocal(node, targetId) {
    if (node.id === targetId) return node;
    if (node.children) {
        for (const child of node.children) {
            const found = findCategoryNodeLocal(child, targetId);
            if (found) return found;
        }
    }
    return null;
}

// Start inline rename
function startInlineRename(element, category) {
    const nameSpan = element.querySelector('.category-name');
    if (!nameSpan) return;

    const oldName = category.name;
    const input = document.createElement('input');
    input.type = 'text';
    input.value = oldName;
    input.className = 'category-rename-input';
    input.style.cssText = `
        font-size: inherit;
        padding: 2px 4px;
        border: 1px solid #007bff;
        border-radius: 3px;
        outline: none;
        width: ${Math.max(nameSpan.offsetWidth + 20, 100)}px;
        background: white;
    `;

    nameSpan.style.display = 'none';
    nameSpan.parentNode.insertBefore(input, nameSpan.nextSibling);
    input.focus();
    input.select();

    const finishRename = async () => {
        const newName = input.value.trim();
        input.remove();
        nameSpan.style.display = '';

        if (newName && newName !== oldName) {
            await renameCategory(category.id, newName);
        }
    };

    input.addEventListener('blur', finishRename);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            input.blur();
        }
        if (e.key === 'Escape') {
            input.value = oldName;
            input.blur();
        }
    });
}

// Add new categories inline
function startInlineAddCategory(parentId) {
    // Find the container of the parent category
    let parentContainer;
    let insertPosition;
    let level = 0;

    if (parentId === 'root') {
        // Add in root directory
        parentContainer = categoryTree;
        insertPosition = parentContainer.firstChild;
        level = 0;
    } else {
        // Add in subdirectory
        const parentElement = document.querySelector(`[data-category-id="${parentId}"]`);
        if (!parentElement) {
            showMessage('Parent category not found', 'error');
            return;
        }

        level = parseInt(parentElement.dataset.level || '0') + 1;
        const parentCategoryContainer = parentElement.closest('.category-container');

        // Make sure the parent category is expanded
        const childrenContainer = parentCategoryContainer.querySelector('.category-children');
        const toggle = parentElement.querySelector('.category-toggle');

        if (childrenContainer) {
            childrenContainer.classList.remove('collapsed');
            if (toggle) {
                toggle.classList.add('expanded');
            }
            expandedCategories.add(parentId);
            parentContainer = childrenContainer;
            insertPosition = parentContainer.firstChild;
        } else {
            // If there is no subcategory container, create one
            const newChildrenContainer = document.createElement('div');
            newChildrenContainer.className = 'category-children';
            parentCategoryContainer.appendChild(newChildrenContainer);

            // Update the expand button of the parent element
            const togglePlaceholder = parentElement.querySelector('.category-toggle-placeholder');
            if (togglePlaceholder) {
                togglePlaceholder.outerHTML = '<button class="category-toggle expanded"><i class="fas fa-chevron-right"></i></button>';
                // rebind event
                const newToggle = parentElement.querySelector('.category-toggle');
                if (newToggle) {
                    newToggle.addEventListener('click', (e) => {
                        e.stopPropagation();
                        const category = findCategoryById(categories, parentId);
                        if (category) {
                            toggleCategoryChildren(parentCategoryContainer, category);
                        }
                    });
                }
            }

            expandedCategories.add(parentId);
            parentContainer = newChildrenContainer;
            insertPosition = null;
        }
    }

    // Create a temporary new category container
    const tempContainer = document.createElement('div');
    tempContainer.className = 'category-container temp-new-category';

    const tempDiv = document.createElement('div');
    tempDiv.className = 'category-item editing';
    tempDiv.dataset.parentId = parentId;
    tempDiv.style.paddingLeft = `${level * 20 + 12}px`;

    // Temporary expand button
    tempDiv.innerHTML = `
        <span class="category-toggle-placeholder"></span>
        <i class="fas fa-folder" style="margin-right: 6px; color: #7d4a9d; font-size: 12px;"></i>
        <span class="category-name" style="display: none;"></span>
        <span class="pdf-count">0</span>
    `;

    tempContainer.appendChild(tempDiv);

    // Insert into appropriate position
    if (insertPosition) {
        parentContainer.insertBefore(tempContainer, insertPosition);
    } else {
        parentContainer.appendChild(tempContainer);
    }

    // Create input box
    const input = document.createElement('input');
    input.type = 'text';
    input.placeholder = 'Enter category name';
    input.className = 'category-rename-input';
    input.style.cssText = `
        font-size: inherit;
        padding: 2px 4px;
        border: 1px solid #28a745;
        border-radius: 3px;
        outline: none;
        width: 150px;
        background: white;
        box-shadow: 0 0 0 2px rgba(40, 167, 69, 0.1);
    `;

    const nameSpan = tempDiv.querySelector('.category-name');
    nameSpan.parentNode.insertBefore(input, nameSpan.nextSibling);
    input.focus();

    // Complete add or cancel
    const finishAdd = async () => {
        const newName = input.value.trim();

        if (newName) {
            // Create new category
            try {
                const response = await fetch('/api/categories', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        parent_id: parentId,
                        name: newName
                    })
                });

                const result = await response.json();

                if (result.success) {
                    showMessage('Category added successfully', 'success');
                    // Remove temporary elements
                    tempContainer.remove();
                    // Update and re-render
                    await updateCategoriesData();
                    await renderCategoryTreeWithState();
                } else {
                    showMessage(`Add failed: ${result.error}`, 'error');
                    tempContainer.remove();
                }
            } catch (error) {
                console.error('Failed to add category:', error);
                showMessage('Failed to add category', 'error');
                tempContainer.remove();
            }
        } else {
            // The user cancels or the input is empty, remove the temporary element
            tempContainer.remove();
        }
    };

    // Completed when focus is lost
    input.addEventListener('blur', finishAdd);

    // Keyboard events
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229) {
            e.preventDefault();
            input.blur();
        }
        if (e.key === 'Escape') {
            input.value = ''; // Clear the input to cancel
            input.blur();
        }
    });
}

function updateBatchUI() {
    const toolbar = document.getElementById('batch-toolbar');
    const btn = document.getElementById('toggle-multiselect');
    const count = document.getElementById('batch-count');
    if (toolbar) toolbar.style.display = isMultiSelectMode ? 'flex' : 'none';
    if (btn) btn.classList.toggle('active', isMultiSelectMode);
    if (count) count.textContent = `selected ${selectedPaperIds.size} item`;
}

function handleMultiSelectClick(e, paperId) {
    const ids = window.__currentSortedPapers || papers.map(p => p.id);
    const index = ids.indexOf(paperId);
    const checkbox = e.target && (e.target.matches('input[type="checkbox"]') || (e.target.closest && e.target.closest('.paper-checkbox')));
    const withShift = e.shiftKey;
    if (withShift && lastSelectedIndex !== null) {
        // Select interval
        const [start, end] = index > lastSelectedIndex ? [lastSelectedIndex, index] : [index, lastSelectedIndex];
        for (let i = start; i <= end; i++) selectedPaperIds.add(ids[i]);
    } else {
        // Switch current item
        if (selectedPaperIds.has(paperId) && !checkbox) {
            selectedPaperIds.delete(paperId);
        } else {
            selectedPaperIds.add(paperId);
        }
        lastSelectedIndex = index;
    }
    updateBatchUI();
    renderPapersList();
}

async function onBatchAnalyze() {
    if (selectedPaperIds.size === 0) { showMessage('Please select a paper first', 'warning'); return; }
    const ids = Array.from(selectedPaperIds);
    for (const id of ids) {
        await requestAnalysis(id);
    }
    // Interpretation has been submitted and the status column will be automatically updated.
}

async function onBatchTranslate() {
    if (selectedPaperIds.size === 0) { showMessage('Please select a paper first', 'warning'); return; }

    // Check user's AI output language setting first
    const userSettings = await getUserSettings();
    const aiLanguage = (userSettings && userSettings.aiLanguage) ? userSettings.aiLanguage : 'zh';

    // If AI output language is English, translation is not needed (papers are already in English)
    if (aiLanguage && aiLanguage.toLowerCase() === 'en') {
        showMessage('Current AI output language is English, and the papers are already in English. Translation is not needed.', 'warning');
        return;
    }

    const ids = Array.from(selectedPaperIds);
    for (const id of ids) {
        await requestTranslation(id);
    }
    // Translation has been submitted, the status column will be updated automatically
    updateTaskIndicator();
}

async function onBatchDelete() {
    if (selectedPaperIds.size === 0) { showMessage('Please select a paper first', 'warning'); return; }
    const ids = Array.from(selectedPaperIds);
    // Optimistic update: remove from frontend first
    papers = papers.filter(p => !selectedPaperIds.has(p.id));
    renderPapersList();
    // Call the backend in order to delete
    for (const id of ids) {
        try { await fetch(`/api/paper/${id}`, { method: 'DELETE' }); } catch (e) { console.error(e); }
    }
    showMessage('Batch deletion completed', 'success');
    await updateCategoriesData();
    renderCategoryTreeWithState();
    exitMultiSelectMode();
}

// Paper sorting function
function sortPapers(papers, sortBy) {
    return papers.sort((a, b) => {
        switch (sortBy) {
            case 'upload_date_desc':
                return new Date(b.upload_date) - new Date(a.upload_date);
            case 'upload_date_asc':
                return new Date(a.upload_date) - new Date(b.upload_date);
            case 'title_asc':
                const titleA = (a.title || a.filename || '').toLowerCase();
                const titleB = (b.title || b.filename || '').toLowerCase();
                return titleA.localeCompare(titleB);
            case 'title_desc':
                const titleA2 = (a.title || a.filename || '').toLowerCase();
                const titleB2 = (b.title || b.filename || '').toLowerCase();
                return titleB2.localeCompare(titleA2);
            case 'published_date_desc':
                // according to arXiv Sort by publication date descending（latest first）
                const dateA = a.arxiv_published_date || '';
                const dateB = b.arxiv_published_date || '';
                if (!dateA && !dateB) return 0;
                if (!dateA) return 1;  // Those without dates come next
                if (!dateB) return -1;
                return new Date(dateB) - new Date(dateA);
            case 'published_date_asc':
                // according to arXiv Sort by release date in ascending order（oldest first）
                const dateA2 = a.arxiv_published_date || '';
                const dateB2 = b.arxiv_published_date || '';
                if (!dateA2 && !dateB2) return 0;
                if (!dateA2) return 1;  // Those without dates come next
                if (!dateB2) return -1;
                return new Date(dateA2) - new Date(dateB2);
            case 'authors_asc':
                const authorsA = (a.authors || '').toLowerCase();
                const authorsB = (b.authors || '').toLowerCase();
                return authorsA.localeCompare(authorsB);
            case 'authors_desc':
                const authorsA2 = (a.authors || '').toLowerCase();
                const authorsB2 = (b.authors || '').toLowerCase();
                return authorsB2.localeCompare(authorsA2);
            default:
                return new Date(b.upload_date) - new Date(a.upload_date);
        }
    });
}

// ==================== Navigation and settings features ====================

// Set up navigation
function setupNavigation() {
    const navTabs = document.querySelectorAll('.nav-tab');
    navTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const targetTab = tab.dataset.tab;
            switchTab(targetTab);
        });
    });

    // Navigation bar avatar click event
    const navAvatar = document.getElementById('nav-avatar');
    if (navAvatar) {
        navAvatar.addEventListener('click', () => {
            switchTab('setting');
        });
    }

    // Settings page left navigation
    document.addEventListener('click', (e) => {
        const item = e.target.closest && e.target.closest('.setting-nav-item');
        if (!item) return;
        const key = item.getAttribute('data-setting');
        if (key) {
            switchSettingPanel(key);
        }
    });

    // To-read list button
    const btnShowReadingList = document.getElementById('btn-show-reading-list');
    if (btnShowReadingList) {
        btnShowReadingList.addEventListener('click', () => {
            switchTab('paper');
            showReadingList();
        });
    }
}

// Return to main interface
function returnToHome() {
    // switch to Paper view
    switchTab('paper');

    // Clear category selection status
    currentCategoryId = null;
    currentViewMode = 'category';

    // Clear selection in category tree
    document.querySelectorAll('.category-item.selected').forEach(item => {
        item.classList.remove('selected');
    });

    // Clear paper selection status
    currentPaperId = null;
    document.querySelectorAll('.paper-item.selected').forEach(item => {
        item.classList.remove('selected');
    });

    // Clear multiple selection mode
    if (isMultiSelectMode) {
        exitMultiSelectMode();
    }

    // Show to-read list
    showReadingList();

    // Save view state
    saveCurrentViewState();
}

// Switch tabs
function switchTab(tabName) {
    const paperView = document.getElementById('paper-view');
    const settingView = document.getElementById('setting-view');
    const dailyArxivView = document.getElementById('daily-arxiv-view');
    const navTabs = document.querySelectorAll('.nav-tab');
    const navAvatar = document.getElementById('nav-avatar');

    // If not switching to Daily arXiv, stop polling
    if (tabName !== 'daily-arxiv' && typeof stopAllDailyArxivPolling === 'function') {
        stopAllDailyArxivPolling();
    }

    navTabs.forEach(tab => {
        if (tab.dataset.tab === tabName) {
            tab.classList.add('active');
        } else {
            tab.classList.remove('active');
        }
    });

    // Update avatar navigation status
    if (navAvatar) {
        if (tabName === 'setting') {
            navAvatar.classList.add('active');
        } else {
            navAvatar.classList.remove('active');
        }
    }

    if (tabName === 'paper') {
        paperView.style.display = 'flex';
        settingView.style.display = 'none';
        if (dailyArxivView) dailyArxivView.style.display = 'none';
        // Not called renderRecentIfNoCategory, letting the caller decide what to display
    } else if (tabName === 'setting') {
        paperView.style.display = 'none';
        settingView.style.display = 'flex';
        if (dailyArxivView) dailyArxivView.style.display = 'none';
        // initialization Settings page
        initSettingsPage();
    } else if (tabName === 'daily-arxiv') {
        paperView.style.display = 'none';
        settingView.style.display = 'none';
        if (dailyArxivView) dailyArxivView.style.display = 'block';
        // initialization Daily arXiv page
        showDailyArxivView();
        return; // showDailyArxivView Will save the state by itself
    }
    saveCurrentViewState();
}

// Save translation settings
// ========== Agentic set up（unifiedAIFunction configuration）==========
async function saveAgenticSettings(silent = false) {
    const translateModelEl = document.getElementById('llm-translate-model');
    const translateBaseUrlEl = document.getElementById('llm-translate-base-url');
    const translateApiKeyEl = document.getElementById('llm-translate-api-key');

    const interpretModelEl = document.getElementById('llm-interpret-model');
    const interpretBaseUrlEl = document.getElementById('llm-interpret-base-url');
    const interpretApiKeyEl = document.getElementById('llm-interpret-api-key');

    const dailyArxivModelEl = document.getElementById('llm-dailyArxiv-model');
    const dailyArxivBaseUrlEl = document.getElementById('llm-dailyArxiv-base-url');
    const dailyArxivApiKeyEl = document.getElementById('llm-dailyArxiv-api-key');

    const mineruEl = document.getElementById('mineru-server-url');
    const mineruApiTokenEl = document.getElementById('mineru-api-token');

    // Check if element exists
    if (
        !translateModelEl || !translateBaseUrlEl || !translateApiKeyEl ||
        !interpretModelEl || !interpretBaseUrlEl || !interpretApiKeyEl ||
        !dailyArxivModelEl || !dailyArxivBaseUrlEl || !dailyArxivApiKeyEl ||
        !mineruEl
    ) {
        console.error('Failed to save settings: Settings input element not found');
        if (!silent) {
            showMessage('Save failed: Settings input element not found', 'error');
        }
        return;
    }

    // Get MinerU mode
    const mineruModeChecked = document.querySelector('input[name="mineru-mode"]:checked');
    const mineruUseApi = mineruModeChecked ? mineruModeChecked.value === 'api' : false;

    const settings = {
        llmConfigs: {
            translate: {
                llmModel: translateModelEl.value.trim(),
                llmBaseUrl: translateBaseUrlEl.value.trim(),
                llmApiKey: translateApiKeyEl.value.trim(),
            },
            interpret: {
                llmModel: interpretModelEl.value.trim(),
                llmBaseUrl: interpretBaseUrlEl.value.trim(),
                llmApiKey: interpretApiKeyEl.value.trim(),
            },
            dailyArxiv: {
                llmModel: dailyArxivModelEl.value.trim(),
                llmBaseUrl: dailyArxivBaseUrlEl.value.trim(),
                llmApiKey: dailyArxivApiKeyEl.value.trim(),
            }
        },
        mineruServerUrl: mineruEl.value.trim(),
        mineruUseApi: mineruUseApi,
        mineruApiToken: mineruApiTokenEl ? mineruApiTokenEl.value.trim() : ''
    };

    console.log('[Save settings] ready to save:', {
        translate: settings.llmConfigs.translate.llmModel ? '***' : '(null)',
        interpret: settings.llmConfigs.interpret.llmModel ? '***' : '(null)',
        dailyArxiv: settings.llmConfigs.dailyArxiv.llmModel ? '***' : '(null)',
        mineruServerUrl: settings.mineruServerUrl ? '***' : '(null)',
        mineruUseApi: settings.mineruUseApi,
        mineruApiToken: settings.mineruApiToken ? '***' : '(null)'
    });

    try {
        const response = await fetch('/api/settings/agentic', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });

        const result = await response.json();

        if (response.ok && result.success) {
            console.log('[Save settings] ✅ Saved successfully');
            // renew Daily arXiv of LLM configuration status
            if (typeof checkDailyArxivLLMConfig === 'function') {
                await checkDailyArxivLLMConfig();
                // If the configuration is complete, re-render the grid to update the button state
                if (typeof renderDailyArxivGrid === 'function') {
                    renderDailyArxivGrid();
                }
            }

            if (!silent) {
                showMessage('AIFunction settings saved', 'success');
            }
        } else {
            const errorMsg = result.error || 'Save failed';
            console.error('[Save settings] ❌ Save failed:', errorMsg);
            if (!silent) {
                showMessage(`Save failed: ${errorMsg}`, 'error');
            }
        }
    } catch (e) {
        console.error('[Save settings] ❌ Save exception:', e);
        if (!silent) {
            showMessage(`Save failed: ${e.message}`, 'error');
        }
    }
}

// Anti-shake function
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Auto save Agentic set up（Anti-shake）
const autoSaveAgenticSettings = debounce(() => {
    saveAgenticSettings(true); // silent mode
}, 500);

// load Agentic set up
async function loadAgenticSettings() {
    try {
        const response = await fetch('/api/settings/agentic');
        if (response.ok) {
            const settings = await response.json();
            const translateModelEl = document.getElementById('llm-translate-model');
            const translateBaseUrlEl = document.getElementById('llm-translate-base-url');
            const translateApiKeyEl = document.getElementById('llm-translate-api-key');

            const interpretModelEl = document.getElementById('llm-interpret-model');
            const interpretBaseUrlEl = document.getElementById('llm-interpret-base-url');
            const interpretApiKeyEl = document.getElementById('llm-interpret-api-key');

            const dailyArxivModelEl = document.getElementById('llm-dailyArxiv-model');
            const dailyArxivBaseUrlEl = document.getElementById('llm-dailyArxiv-base-url');
            const dailyArxivApiKeyEl = document.getElementById('llm-dailyArxiv-api-key');

            const mineruEl = document.getElementById('mineru-server-url');
            const mineruApiTokenEl = document.getElementById('mineru-api-token');
            const promptEl = document.getElementById('analysis-system-prompt');

            const legacyFallback = {
                llmModel: settings.llmModel || '',
                llmBaseUrl: settings.llmBaseUrl || '',
                llmApiKey: settings.llmApiKey || ''
            };
            const llmConfigs = settings.llmConfigs || {};
            const translateCfg = llmConfigs.translate || legacyFallback;
            const interpretCfg = llmConfigs.interpret || legacyFallback;
            const dailyArxivCfg = llmConfigs.dailyArxiv || legacyFallback;

            if (translateModelEl) {
                translateModelEl.value = translateCfg.llmModel || '';
                translateModelEl.addEventListener('input', autoSaveAgenticSettings);
            }
            if (translateBaseUrlEl) {
                translateBaseUrlEl.value = translateCfg.llmBaseUrl || '';
                translateBaseUrlEl.addEventListener('input', autoSaveAgenticSettings);
            }
            if (translateApiKeyEl) {
                translateApiKeyEl.value = translateCfg.llmApiKey || '';
                translateApiKeyEl.addEventListener('input', autoSaveAgenticSettings);
            }

            if (interpretModelEl) {
                interpretModelEl.value = interpretCfg.llmModel || '';
                interpretModelEl.addEventListener('input', autoSaveAgenticSettings);
            }
            if (interpretBaseUrlEl) {
                interpretBaseUrlEl.value = interpretCfg.llmBaseUrl || '';
                interpretBaseUrlEl.addEventListener('input', autoSaveAgenticSettings);
            }
            if (interpretApiKeyEl) {
                interpretApiKeyEl.value = interpretCfg.llmApiKey || '';
                interpretApiKeyEl.addEventListener('input', autoSaveAgenticSettings);
            }

            if (dailyArxivModelEl) {
                dailyArxivModelEl.value = dailyArxivCfg.llmModel || '';
                dailyArxivModelEl.addEventListener('input', autoSaveAgenticSettings);
            }
            if (dailyArxivBaseUrlEl) {
                dailyArxivBaseUrlEl.value = dailyArxivCfg.llmBaseUrl || '';
                dailyArxivBaseUrlEl.addEventListener('input', autoSaveAgenticSettings);
            }
            if (dailyArxivApiKeyEl) {
                dailyArxivApiKeyEl.value = dailyArxivCfg.llmApiKey || '';
                dailyArxivApiKeyEl.addEventListener('input', autoSaveAgenticSettings);
            }
            if (mineruEl) {
                mineruEl.value = settings.mineruServerUrl || '';
                mineruEl.addEventListener('input', autoSaveAgenticSettings);
            }
            if (mineruApiTokenEl) {
                mineruApiTokenEl.value = settings.mineruApiToken || '';
                mineruApiTokenEl.addEventListener('input', autoSaveAgenticSettings);
            }

            // Set MinerU mode radio buttons
            const mineruUseApi = settings.mineruUseApi || false;
            const localRadio = document.querySelector('input[name="mineru-mode"][value="local"]');
            const apiRadio = document.querySelector('input[name="mineru-mode"][value="api"]');

            if (localRadio && apiRadio) {
                if (mineruUseApi) {
                    apiRadio.checked = true;
                } else {
                    localRadio.checked = true;
                }

                // Add event listeners for mode change
                localRadio.addEventListener('change', () => {
                    toggleMineruConfigUI();
                    autoSaveAgenticSettings();
                });
                apiRadio.addEventListener('change', () => {
                    toggleMineruConfigUI();
                    autoSaveAgenticSettings();
                });

                // Initial UI toggle
                toggleMineruConfigUI();
            }

            // Bind test button event
            const testTranslateBtn = document.getElementById('test-llm-api-translate');
            const testInterpretBtn = document.getElementById('test-llm-api-interpret');
            const testDailyArxivBtn = document.getElementById('test-llm-api-dailyArxiv');
            const testMineruBtns = document.querySelectorAll('#test-mineru-btn');

            if (testTranslateBtn) {
                testTranslateBtn.addEventListener('click', () => testLLMAPIByScenario('translate'));
            }
            if (testInterpretBtn) {
                testInterpretBtn.addEventListener('click', () => testLLMAPIByScenario('interpret'));
            }
            if (testDailyArxivBtn) {
                testDailyArxivBtn.addEventListener('click', () => testLLMAPIByScenario('dailyArxiv'));
            }
            // Both test buttons should use the same handler
            testMineruBtns.forEach(btn => {
                btn.addEventListener('click', testMineruAPI);
            });

            // Load AI language setting from user settings
            await loadAILanguageSetting();
        }
    } catch (e) {
        console.error('loadAIFunction setting failed:', e);
    }
}

// Toggle MinerU config UI based on selected mode
function toggleMineruConfigUI() {
    try {
        const mode = document.querySelector('input[name="mineru-mode"]:checked');
        const modeValue = mode ? mode.value : 'local';

        const localConfig = document.getElementById('mineru-local-config');
        const apiConfig = document.getElementById('mineru-api-config');

        if (localConfig && apiConfig) {
            if (modeValue === 'api') {
                localConfig.style.display = 'none';
                apiConfig.style.display = 'block';
            } else {
                localConfig.style.display = 'block';
                apiConfig.style.display = 'none';
            }
        }
    } catch (e) {
        console.error('Error in toggleMineruConfigUI:', e);
    }
}

// Load AI language setting and bind to select element
async function loadAILanguageSetting() {
    try {
        const userSettings = await getUserSettings();
        const aiLanguage = userSettings.aiLanguage || 'zh';

        // Set value in Agentic settings panel
        const aiLanguageEl = document.getElementById('ai-language');
        if (aiLanguageEl) {
            aiLanguageEl.value = aiLanguage;
            // Bind change event to save setting
            aiLanguageEl.addEventListener('change', async () => {
                const selectedLanguage = aiLanguageEl.value;
                await saveUserSettings({ aiLanguage: selectedLanguage });
                console.log('[Settings] AI language saved:', selectedLanguage);
            });
        }
    } catch (e) {
        console.error('Failed to load AI language setting:', e);
    }
}

// test LLM API（Core logic, reusable）
async function testLLMAPICore(llmModel, llmBaseUrl, llmApiKey, llmConfigType = null) {
    if (!llmModel || !llmBaseUrl || !llmApiKey) {
        return {
            success: false,
            error: 'Please fill in the complete LLM API Configuration（Model、Base URL、API Key）'
        };
    }

    try {
        const payload = {
            llmModel: llmModel,
            llmBaseUrl: llmBaseUrl,
            llmApiKey: llmApiKey
        };
        if (llmConfigType) {
            payload.llmConfigType = llmConfigType;
        }
        const response = await fetch('/api/settings/test/llm', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await response.json();
        return data;
    } catch (error) {
        return {
            success: false,
            error: `network error: ${error.message}`
        };
    }
}

async function testLLMAPIByScenario(scenarioKey) {
    const btn = document.getElementById(`test-llm-api-${scenarioKey}`);
    const resultDiv = document.getElementById(`llm-test-result-${scenarioKey}`);

    if (!btn || !resultDiv) return;

    const modelEl = document.getElementById(`llm-${scenarioKey}-model`);
    const baseUrlEl = document.getElementById(`llm-${scenarioKey}-base-url`);
    const apiKeyEl = document.getElementById(`llm-${scenarioKey}-api-key`);

    if (!modelEl || !baseUrlEl || !apiKeyEl) return;

    const llmModel = modelEl.value.trim();
    const llmBaseUrl = baseUrlEl.value.trim();
    const llmApiKey = apiKeyEl.value.trim();

    if (!llmModel || !llmBaseUrl || !llmApiKey) {
        resultDiv.innerHTML = `
            <div style="padding: 12px; background: #fff3cd; border: 1px solid #ffc107; border-radius: 6px; color: #856404;">
                <i class="fas fa-exclamation-triangle"></i> Please fill in the complete LLM API Configuration
            </div>
        `;
        resultDiv.style.display = 'block';
        return;
    }

    const originalHTML = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Under test...';
    resultDiv.style.display = 'block';
    resultDiv.innerHTML = `
        <div style="padding: 12px; background: #e7f3ff; border: 1px solid #2196F3; border-radius: 6px; color: #0d47a1;">
            <i class="fas fa-spinner fa-spin"></i> Testing LLM API connect...
        </div>
    `;

    const data = await testLLMAPICore(llmModel, llmBaseUrl, llmApiKey, scenarioKey);

    if (data.success) {
        resultDiv.innerHTML = `
            <div style="padding: 12px; background: #d4edda; border: 1px solid #28a745; border-radius: 6px; color: #155724;">
                <i class="fas fa-check-circle"></i> <strong>${data.message}</strong>
                ${data.reply ? `<div style="margin-top: 8px; font-size: 13px;">reply: "${data.reply}"</div>` : ''}
            </div>
        `;
    } else {
        resultDiv.innerHTML = `
            <div style="padding: 12px; background: #f8d7da; border: 1px solid #dc3545; border-radius: 6px; color: #721c24;">
                <i class="fas fa-times-circle"></i> <strong>test failed</strong>
                <div style="margin-top: 8px; font-size: 13px;">${data.error || 'unknown error'}</div>
            </div>
        `;
    }

    btn.disabled = false;
    btn.innerHTML = originalHTML;
}

async function testLLMAPI() {
    return testLLMAPIByScenario('interpret');
}

// test MinerU API
async function testMineruAPI(event) {
    // Find the test button that was clicked (could be in either local or API config)
    const btn = event && event.currentTarget ? event.currentTarget : document.getElementById('test-mineru-btn');
    const resultDiv = document.getElementById('mineru-test-result');

    if (!btn || !resultDiv) return;

    // Get current mode
    const mode = document.querySelector('input[name="mineru-mode"]:checked');
    const modeValue = mode ? mode.value : 'local';

    // Update button state
    const originalHTML = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Under test...';
    resultDiv.style.display = 'block';

    if (modeValue === 'local') {
        // Test local server
        const mineruServerUrl = document.getElementById('mineru-server-url').value.trim();

        if (!mineruServerUrl) {
            resultDiv.innerHTML = `
                <div style="padding: 12px; background: #fff3cd; border: 1px solid #ffc107; border-radius: 6px; color: #856404;">
                    <i class="fas fa-exclamation-triangle"></i> Please fill in first MinerU Server URL
                </div>
            `;
            resultDiv.style.display = 'block';
            btn.disabled = false;
            btn.innerHTML = originalHTML;
            return;
        }

        resultDiv.innerHTML = `
            <div style="padding: 12px; background: #e7f3ff; border: 1px solid #2196F3; border-radius: 6px; color: #0d47a1;">
                <i class="fas fa-spinner fa-spin"></i> Testing MinerU Server connect...
            </div>
        `;

        try {
            const response = await fetch('/api/settings/test/mineru', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    mineruServerUrl: mineruServerUrl
                })
            });

            const data = await response.json();

            if (data.success) {
                resultDiv.innerHTML = `
                    <div style="padding: 12px; background: #d4edda; border: 1px solid #28a745; border-radius: 6px; color: #155724;">
                        <i class="fas fa-check-circle"></i> <strong>${data.message}</strong>
                        ${data.tested_url ? `<div style="margin-top: 8px; font-size: 13px;">Test address: ${data.tested_url}</div>` : ''}
                    </div>
                `;
            } else {
                resultDiv.innerHTML = `
                    <div style="padding: 12px; background: #f8d7da; border: 1px solid #dc3545; border-radius: 6px; color: #721c24;">
                        <i class="fas fa-times-circle"></i> <strong>test failed</strong>
                        <div style="margin-top: 8px; font-size: 13px;">${data.error || 'unknown error'}</div>
                    </div>
                `;
            }
        } catch (error) {
            resultDiv.innerHTML = `
                <div style="padding: 12px; background: #f8d7da; border: 1px solid #dc3545; border-radius: 6px; color: #721c24;">
                    <i class="fas fa-times-circle"></i> <strong>test failed</strong>
                    <div style="margin-top: 8px; font-size: 13px;">${error.message}</div>
                </div>
            `;
        }
    } else {
        // Test API token
        const mineruApiToken = document.getElementById('mineru-api-token').value.trim();

        if (!mineruApiToken) {
            resultDiv.innerHTML = `
                <div style="padding: 12px; background: #fff3cd; border: 1px solid #ffc107; border-radius: 6px; color: #856404;">
                    <i class="fas fa-exclamation-triangle"></i> Please enter API token
                </div>
            `;
            resultDiv.style.display = 'block';
            btn.disabled = false;
            btn.innerHTML = originalHTML;
            return;
        }

        resultDiv.innerHTML = `
            <div style="padding: 12px; background: #e7f3ff; border: 1px solid #2196F3; border-radius: 6px; color: #0d47a1;">
                <i class="fas fa-spinner fa-spin"></i> Testing MinerU API Token...
            </div>
        `;

        try {
            const response = await fetch('/api/settings/test/mineru-api', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    apiToken: mineruApiToken
                })
            });

            const data = await response.json();

            if (data.success) {
                resultDiv.innerHTML = `
                    <div style="padding: 12px; background: #d4edda; border: 1px solid #28a745; border-radius: 6px; color: #155724;">
                        <i class="fas fa-check-circle"></i> <strong>${data.message}</strong>
                    </div>
                `;
            } else {
                resultDiv.innerHTML = `
                    <div style="padding: 12px; background: #f8d7da; border: 1px solid #dc3545; border-radius: 6px; color: #721c24;">
                        <i class="fas fa-times-circle"></i> <strong>test failed</strong>
                        <div style="margin-top: 8px; font-size: 13px;">${data.error || 'unknown error'}</div>
                    </div>
                `;
            }
        } catch (error) {
            resultDiv.innerHTML = `
                <div style="padding: 12px; background: #f8d7da; border: 1px solid #dc3545; border-radius: 6px; color: #721c24;">
                    <i class="fas fa-times-circle"></i> <strong>test failed</strong>
                    <div style="margin-top: 8px; font-size: 13px;">${error.message}</div>
                </div>
            `;
        }
    }

    btn.disabled = false;
    btn.innerHTML = originalHTML;
}

// get Agentic set up
async function getAgenticSettings() {
    try {
        const response = await fetch('/api/settings/agentic');
        if (response.ok) {
            return await response.json();
        }
    } catch (e) {
        console.error('getAIFunction setting failed:', e);
    }
    return null;
}

function getAgenticLLMConfig(settings, scenarioKey) {
    const empty = { llmModel: '', llmBaseUrl: '', llmApiKey: '' };
    if (!settings) return empty;

    const llmConfigs = settings.llmConfigs;
    if (llmConfigs && typeof llmConfigs === 'object') {
        const cfg = llmConfigs[scenarioKey];
        if (cfg && typeof cfg === 'object') {
            return {
                llmModel: (cfg.llmModel || '').trim(),
                llmBaseUrl: (cfg.llmBaseUrl || '').trim(),
                llmApiKey: (cfg.llmApiKey || '').trim(),
            };
        }
    }

    return {
        llmModel: (settings.llmModel || '').trim(),
        llmBaseUrl: (settings.llmBaseUrl || '').trim(),
        llmApiKey: (settings.llmApiKey || '').trim(),
    };
}

function isAgenticLLMConfigured(cfg) {
    return !!(cfg && cfg.llmModel && cfg.llmBaseUrl && cfg.llmApiKey);
}

// ========== Deprecated setup function（reserved for compatibility） ==========
async function saveTranslationSettings() {
    console.warn('saveTranslationSettings is deprecated, use saveAgenticSettings instead');
    return saveAgenticSettings();
}

async function loadTranslationSettings() {
    console.warn('loadTranslationSettings is deprecated, use loadAgenticSettings instead');
    return loadAgenticSettings();
}

async function getTranslationSettings() {
    console.warn('getTranslationSettings is deprecated, use getAgenticSettings instead');
    return getAgenticSettings();
}

// ==================== Translation function ====================

// ========== General set up（Deprecated）==========
async function saveGeneralSettings() {
    console.warn('saveGeneralSettings is deprecated, General settings have been removed');
    showMessage('General Setting is obsolete', 'warning');
}

async function loadGeneralSettings() {
    console.warn('loadGeneralSettings is deprecated, General settings have been removed');
}

// ========================================
// Settings page - Heatmaps and statistics
// ========================================

let settingsNavInitialized = false;
let currentHeatmapYear = new Date().getFullYear();

// ========================================
// User avatar and name settings
// ========================================

// Generate pixel avatar (GitHub style identicon)
function generateIdenticon(seed, size = 5) {
    // Simple hash function
    let hash = 0;
    for (let i = 0; i < seed.length; i++) {
        const char = seed.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash;
    }

    // Generate color - Use a seed to generate a nice color
    const hue = Math.abs(hash % 360);
    const saturation = 65 + Math.abs((hash >> 8) % 20);
    const lightness = 45 + Math.abs((hash >> 16) % 15);
    const bgColor = `hsl(${hue}, ${saturation}%, ${lightness}%)`;
    const fgColor = `hsl(${hue}, ${saturation}%, ${lightness + 35}%)`;

    // Generate pixel patterns (5x5 symmetry)
    const pattern = [];
    for (let y = 0; y < size; y++) {
        pattern[y] = [];
        for (let x = 0; x < Math.ceil(size / 2); x++) {
            // Use different bits of the hash value to determine the pixel
            const bitIndex = y * 3 + x;
            const pixel = (Math.abs(hash >> bitIndex) % 2) === 1;
            pattern[y][x] = pixel;
            // mirror
            pattern[y][size - 1 - x] = pixel;
        }
    }

    return { pattern, bgColor, fgColor, size };
}

// exist canvas Draw pixel avatar on
function drawIdenticon(canvas, seed) {
    const ctx = canvas.getContext('2d');
    const { pattern, bgColor, fgColor, size } = generateIdenticon(seed);

    const cellSize = canvas.width / size;

    // draw background
    ctx.fillStyle = bgColor;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // draw pixels
    ctx.fillStyle = fgColor;
    for (let y = 0; y < size; y++) {
        for (let x = 0; x < size; x++) {
            if (pattern[y][x]) {
                ctx.fillRect(
                    x * cellSize + cellSize * 0.1,
                    y * cellSize + cellSize * 0.1,
                    cellSize * 0.8,
                    cellSize * 0.8
                );
            }
        }
    }
}

// User settings cache（Avoid frequent requests to the backend）
let userSettingsCache = null;

// Get user settings（asynchronous）
async function getUserSettings() {
    // If there is cache, return directly
    if (userSettingsCache) {
        return userSettingsCache;
    }
    try {
        const response = await fetch('/api/settings/user');
        if (response.ok) {
            userSettingsCache = await response.json();
            return userSettingsCache;
        }
    } catch (e) {
        console.error('Failed to read user settings:', e);
    }
    return {
        name: 'Paper Reader',
        avatar: null,
        heatmapColorScheme: 'green',
        onboardingDontShow: false
    };
}

// Get user settings（Sync version, use cache）
function getUserSettingsSync() {
    if (userSettingsCache) {
        return userSettingsCache;
    }
    return {
        name: 'Paper Reader',
        avatar: null,
        heatmapColorScheme: 'green',
        onboardingDontShow: false
    };
}

// Save user settings
async function saveUserSettings(settings) {
    try {
        const response = await fetch('/api/settings/user', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
        if (response.ok) {
            // Update cache
            userSettingsCache = { ...userSettingsCache, ...settings };
        }
    } catch (e) {
        console.error('Failed to save user settings:', e);
    }
}

// Upload avatar to server
async function uploadAvatar(avatarData) {
    try {
        const response = await fetch('/api/settings/avatar', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ avatarData })
        });
        if (response.ok) {
            const result = await response.json();
            // Update cache
            if (userSettingsCache) {
                userSettingsCache.avatar = result.avatar;
            }
            return result.avatar;
        }
    } catch (e) {
        console.error('Failed to upload avatar:', e);
    }
    return null;
}

// Update all avatar displays
async function updateAvatars() {
    const userSettings = await getUserSettings();

    // Draw avatar to canvas auxiliary function
    const drawAvatarToCanvas = async (canvas, avatarUrl, userName) => {
        if (avatarUrl) {
            try {
                // Use fetch to load image with Authorization header
                const response = await fetch(avatarUrl + '?t=' + Date.now());
                if (!response.ok) throw new Error('Failed to load avatar');
                const blob = await response.blob();
                const objectUrl = URL.createObjectURL(blob);

                const img = new Image();
                img.onload = () => {
                    const ctx = canvas.getContext('2d');
                    ctx.clearRect(0, 0, canvas.width, canvas.height);
                    // round cut
                    ctx.save();
                    ctx.beginPath();
                    ctx.arc(canvas.width / 2, canvas.height / 2, canvas.width / 2, 0, Math.PI * 2);
                    ctx.closePath();
                    ctx.clip();
                    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                    ctx.restore();
                    URL.revokeObjectURL(objectUrl);
                };
                img.onerror = () => {
                    // Use pixel avatar when loading fails
                    drawIdenticon(canvas, userName);
                    URL.revokeObjectURL(objectUrl);
                };
                img.src = objectUrl;
            } catch (e) {
                console.error('Avatar load error:', e);
                drawIdenticon(canvas, userName);
            }
        } else {
            // Use generated pixel avatar
            drawIdenticon(canvas, userName);
        }
    };

    const avatarUrl = userSettings.avatar ? '/api/settings/avatar' : null;

    // Navigation bar avatar
    const navCanvas = document.getElementById('nav-avatar-canvas');
    if (navCanvas) {
        drawAvatarToCanvas(navCanvas, avatarUrl, userSettings.name);
    }

    // Settings Page avatar
    const settingCanvas = document.getElementById('setting-avatar-canvas');
    if (settingCanvas) {
        drawAvatarToCanvas(settingCanvas, avatarUrl, userSettings.name);
    }

    // Update name display
    const nameEl = document.getElementById('setting-user-name');
    if (nameEl) {
        nameEl.textContent = userSettings.name;
    }
}

// Set event listeners for user avatar and name
function setupUserProfileEvents() {
    // Avatar upload
    const settingAvatar = document.getElementById('setting-user-avatar');
    const avatarUpload = document.getElementById('avatar-upload');

    if (settingAvatar && avatarUpload) {
        settingAvatar.addEventListener('click', () => {
            avatarUpload.click();
        });

        avatarUpload.addEventListener('change', async (e) => {
            const file = e.target.files[0];
            if (file) {
                if (!file.type.startsWith('image/')) {
                    showMessage('Please select image file', 'warning');
                    return;
                }

                const reader = new FileReader();
                reader.onload = async (event) => {
                    const img = new Image();
                    img.onload = async () => {
                        // Compress images to appropriate size
                        const canvas = document.createElement('canvas');
                        const maxSize = 200;
                        let width = img.width;
                        let height = img.height;

                        if (width > height) {
                            if (width > maxSize) {
                                height *= maxSize / width;
                                width = maxSize;
                            }
                        } else {
                            if (height > maxSize) {
                                width *= maxSize / height;
                                height = maxSize;
                            }
                        }

                        canvas.width = width;
                        canvas.height = height;
                        const ctx = canvas.getContext('2d');
                        ctx.drawImage(img, 0, 0, width, height);

                        const avatarData = canvas.toDataURL('image/jpeg', 0.8);

                        // upload to server
                        const result = await uploadAvatar(avatarData);
                        if (result) {
                            await updateAvatars();
                            showMessage('Avatar has been updated', 'success');
                        } else {
                            showMessage('Avatar upload failed', 'error');
                        }
                    };
                    img.src = event.target.result;
                };
                reader.readAsDataURL(file);
            }
        });
    }

    // Name edit (double click)
    const nameEl = document.getElementById('setting-user-name');
    if (nameEl) {
        nameEl.addEventListener('dblclick', () => {
            nameEl.contentEditable = true;
            nameEl.classList.add('editing');
            nameEl.focus();

            // Select text
            const range = document.createRange();
            range.selectNodeContents(nameEl);
            const sel = window.getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
        });

        nameEl.addEventListener('blur', async () => {
            nameEl.contentEditable = false;
            nameEl.classList.remove('editing');

            const newName = nameEl.textContent.trim();
            if (newName) {
                const userSettings = await getUserSettings();
                if (newName !== userSettings.name) {
                    await saveUserSettings({ name: newName });
                    // If there is no custom avatar, regenerate the pixel avatar
                    if (!userSettings.avatar) {
                        await updateAvatars();
                    }
                    showMessage('Name has been updated', 'success');
                }
            } else {
                // Restore original name
                const userSettings = await getUserSettings();
                nameEl.textContent = userSettings.name;
            }
        });

        nameEl.addEventListener('keydown', async (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                nameEl.blur();
            } else if (e.key === 'Escape') {
                const userSettings = await getUserSettings();
                nameEl.textContent = userSettings.name;
                nameEl.blur();
            }
        });
    }
}

// initialization Settings page
async function initSettingsPage() {
    console.log('initialization Settings page, Initialized:', settingsNavInitialized);
    if (!settingsNavInitialized) {
        setupSettingsNavigation();
        setupHeatmapControls();
        setupUserProfileEvents();
        settingsNavInitialized = true;
    }
    // First load user settings and reading history to cache（Force refresh）
    await getUserSettings();
    // Clear cache, force reload from server
    readingHistoryCache = null;
    await getDailyReadingData();
    // Update avatar and name
    await updateAvatars();
    // Load saved color system（Now loading from server）
    await loadHeatmapColorScheme();
    // Update year display
    updateYearDisplay();
    renderHeatmap(currentHeatmapYear);
    renderOverviewStats();
    renderRecentActivity();
}

// Get the year range with reading data
function getReadingYearRange() {
    const historyData = getDailyReadingDataSync();
    const dailyData = getDailyReadingMinutes(historyData);
    const years = new Set();

    Object.keys(dailyData).forEach(dateStr => {
        if (dailyData[dateStr] > 0) {
            const year = parseInt(dateStr.split('-')[0], 10);
            years.add(year);
        }
    });

    if (years.size === 0) {
        // Without any data, returns the current year
        const thisYear = new Date().getFullYear();
        return { minYear: thisYear, maxYear: thisYear };
    }

    const yearArray = Array.from(years).sort((a, b) => a - b);
    return {
        minYear: yearArray[0],
        maxYear: yearArray[yearArray.length - 1]
    };
}

// Set up heat map controls（Year selection, color selection）
function setupHeatmapControls() {
    // Year selection
    const prevBtn = document.getElementById('year-prev');
    const nextBtn = document.getElementById('year-next');

    if (prevBtn) {
        prevBtn.addEventListener('click', () => {
            const { minYear } = getReadingYearRange();
            if (currentHeatmapYear > minYear) {
                currentHeatmapYear--;
                updateYearDisplay();
                renderHeatmap(currentHeatmapYear);
            }
        });
    }

    if (nextBtn) {
        nextBtn.addEventListener('click', () => {
            const thisYear = new Date().getFullYear();
            if (currentHeatmapYear < thisYear) {
                currentHeatmapYear++;
                updateYearDisplay();
                renderHeatmap(currentHeatmapYear);
            }
        });
    }

    // Color selection
    const legend = document.getElementById('heatmap-legend');
    const dropdown = document.getElementById('color-scheme-dropdown');

    if (legend && dropdown) {
        legend.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.toggle('show');
        });

        // Click elsewhere to close the drop-down box
        document.addEventListener('click', (e) => {
            if (!dropdown.contains(e.target) && !legend.contains(e.target)) {
                dropdown.classList.remove('show');
            }
        });

        // Click on color options
        dropdown.querySelectorAll('.color-scheme-option').forEach(option => {
            option.addEventListener('click', () => {
                const scheme = option.dataset.scheme;
                setHeatmapColorScheme(scheme);
                dropdown.classList.remove('show');
            });
        });
    }
}

// Update year display
function updateYearDisplay() {
    const yearEl = document.getElementById('heatmap-year');
    const prevBtn = document.getElementById('year-prev');
    const nextBtn = document.getElementById('year-next');
    const thisYear = new Date().getFullYear();
    const { minYear } = getReadingYearRange();

    if (yearEl) {
        yearEl.textContent = currentHeatmapYear;
    }

    // Disable the previous year button if it is already the earliest year with data
    if (prevBtn) {
        prevBtn.disabled = currentHeatmapYear <= minYear;
    }

    // Disable next year button if it is already this year
    if (nextBtn) {
        nextBtn.disabled = currentHeatmapYear >= thisYear;
    }
}

// Set heat map color system
function setHeatmapColorScheme(scheme, save = true) {
    const container = document.querySelector('.heatmap-container');
    const dropdown = document.getElementById('color-scheme-dropdown');

    if (container) {
        container.setAttribute('data-scheme', scheme);
    }

    // Update selected status
    if (dropdown) {
        dropdown.querySelectorAll('.color-scheme-option').forEach(option => {
            option.classList.toggle('active', option.dataset.scheme === scheme);
        });
    }

    // Save to server
    if (save) {
        saveUserSettings({ heatmapColorScheme: scheme });
        console.log('Color system saved:', scheme);
    }
}

// Load saved color system
async function loadHeatmapColorScheme() {
    const userSettings = await getUserSettings();
    const scheme = userSettings.heatmapColorScheme || 'green';
    setHeatmapColorScheme(scheme, false); // Do not save repeatedly
}

// set up Settings Navigation toggle
function setupSettingsNavigation() {
    const navItems = document.querySelectorAll('.setting-sidebar-nav .setting-nav-item');
    const panels = document.querySelectorAll('.setting-main .setting-panel');

    console.log('Set navigation initialization, navItems:', navItems.length, 'panels:', panels.length);

    navItems.forEach(item => {
        item.addEventListener('click', function (e) {
            e.preventDefault();
            const targetPanel = this.dataset.setting;
            console.log('Click to navigate:', targetPanel);

            // Update navigation status
            navItems.forEach(nav => nav.classList.remove('active'));
            this.classList.add('active');

            // Switch panel
            panels.forEach(panel => {
                if (panel.id === `setting-panel-${targetPanel}`) {
                    panel.style.display = 'block';
                    console.log('display panel:', panel.id);

                    // If you switch to Daily arXiv Panel, load settings and bind events
                    if (targetPanel === 'daily-arxiv') {
                        loadDailyArxivSettings().then(() => {
                            setupDailyArxivKeywordInput();
                        });
                    }
                } else {
                    panel.style.display = 'none';
                }
            });
        });
    });
}

// Format the date as YYYY-MM-DD（Use local time to avoid time zone issues）
function formatDateLocal(date) {
    const d = date || new Date();
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

// Record daily reading time
function recordDailyReadingTime(minutes) {
    const today = formatDateLocal(new Date());

    // Send to server
    fetch('/api/settings/reading-history/record', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ minutes, date: today })
    }).catch(e => {
        console.error('Failed to record daily reading time:', e);
    });

    // Also update local cache（for immediate display）
    if (readingHistoryCache) {
        readingHistoryCache[today] = (readingHistoryCache[today] || 0) + minutes;
    }
}

// Get daily reading data
// Reading history cache
let readingHistoryCache = null;

async function getDailyReadingData() {
    // If there is cache, return directly
    if (readingHistoryCache) {
        return readingHistoryCache;
    }
    try {
        const response = await fetch('/api/settings/reading-history');
        if (response.ok) {
            readingHistoryCache = await response.json();
            return readingHistoryCache;
        }
    } catch (e) {
        console.error('Failed to obtain daily reading data:', e);
    }
    return {};
}

// sync version（Use caching）
function getDailyReadingDataSync() {
    if (readingHistoryCache) {
        return readingHistoryCache;
    }
    return {};
}

// Get daily reading time from reading history（Compatible with old and new formats）
// new format: { "date": { "total": minutes, "papers": [...] } }
// old format: { "date": minutes }
function getDailyReadingMinutes(historyData) {
    const result = {};
    for (const [date, value] of Object.entries(historyData)) {
        if (typeof value === 'object' && value !== null) {
            // new format
            result[date] = value.total || 0;
        } else {
            // old format
            result[date] = value || 0;
        }
    }
    return result;
}

// Add test reading data
async function addTestReadingData() {
    const today = formatDateLocal(new Date());

    try {
        // Add today's test data（30minute）
        await fetch('/api/settings/reading-history/record', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ minutes: 30, date: today })
        });

        // Add random data from the past week
        for (let i = 1; i <= 7; i++) {
            const date = new Date();
            date.setDate(date.getDate() - i);
            const dateStr = formatDateLocal(date);
            const minutes = Math.floor(Math.random() * 60) + 10; // 10-70minute
            await fetch('/api/settings/reading-history/record', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ minutes, date: dateStr })
            });
        }

        // Clear cache and reload
        readingHistoryCache = null;
        await getDailyReadingData();

        console.log('Test data has been added');
        showMessage('Test data has been added and the heat map has been refreshed....', 'success');

        // Refresh heat map
        renderHeatmap();
        renderOverviewStats();
    } catch (e) {
        console.error('Failed to add test data:', e);
        showMessage('Failed to add test data', 'error');
    }
}

// Clear all reading data
async function clearReadingData() {
    if (confirm('Are you sure you want to clear all reading data? This action cannot be undone.')) {
        try {
            await fetch('/api/settings/reading-history/clear', { method: 'POST' });
            readingHistoryCache = null;
            console.log('Reading data cleared');
            showMessage('Reading data cleared', 'success');

            // Refresh heat map
            renderHeatmap();
            renderOverviewStats();
        } catch (e) {
            console.error('Clear data failed:', e);
            showMessage('Clear data failed', 'error');
        }
    }
}

// Render heat map
function renderHeatmap(year) {
    const grid = document.getElementById('heatmap-grid');
    const monthsContainer = document.getElementById('heatmap-months');

    if (!grid || !monthsContainer) {
        console.log('Heatmap element not found', { grid, monthsContainer });
        return;
    }

    year = year || new Date().getFullYear();
    // Use the synchronous cached version, make sure the data has been loaded before calling
    const historyData = getDailyReadingDataSync();
    const data = getDailyReadingMinutes(historyData);
    console.log('Heat map data:', data, 'years:', year);

    const today = new Date();
    const isCurrentYear = year === today.getFullYear();

    // Clear existing content
    grid.innerHTML = '';
    monthsContainer.innerHTML = '';

    // Calculate the start and end dates of the year
    const yearStart = new Date(year, 0, 1);
    const yearEnd = isCurrentYear ? today : new Date(year, 11, 31);

    // Find the Sunday of the week in which the first day of the year falls
    const startDate = new Date(yearStart);
    startDate.setDate(startDate.getDate() - startDate.getDay());

    // Calculate grading threshold for reading time
    const allValues = Object.values(data).filter(v => v > 0);
    let thresholds = [0, 15, 30, 60, 120]; // Default threshold（minute）

    if (allValues.length > 0) {
        const sorted = [...allValues].sort((a, b) => a - b);
        const p25 = sorted[Math.floor(sorted.length * 0.25)] || 15;
        const p50 = sorted[Math.floor(sorted.length * 0.5)] || 30;
        const p75 = sorted[Math.floor(sorted.length * 0.75)] || 60;
        thresholds = [0, p25, p50, p75, p75 * 1.5];
    }

    // Get reading level
    function getLevel(minutes) {
        if (!minutes || minutes <= 0) return 0;
        if (minutes < thresholds[1]) return 1;
        if (minutes < thresholds[2]) return 2;
        if (minutes < thresholds[3]) return 3;
        return 4;
    }

    // Format time
    function formatMinutes(mins) {
        if (mins < 60) return `${mins} minute`;
        const hours = Math.floor(mins / 60);
        const minutes = mins % 60;
        return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
    }

    // month name
    const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

    // Generate month labels（fixed12indivual）
    monthNames.forEach(name => {
        const monthSpan = document.createElement('span');
        monthSpan.textContent = name;
        monthsContainer.appendChild(monthSpan);
    });

    let totalActiveDays = 0;
    let totalYearMinutes = 0;

    // Generate weeks of the entire year
    const currentDate = new Date(startDate);
    const endOfYear = new Date(year, 11, 31);
    // Find the Saturday of the week in which the year ends
    const finalDate = new Date(endOfYear);
    finalDate.setDate(finalDate.getDate() + (6 - finalDate.getDay()));

    while (currentDate <= finalDate) {
        const weekDiv = document.createElement('div');
        weekDiv.className = 'heatmap-week';

        // Generate a week7sky
        for (let day = 0; day < 7; day++) {
            const dayDiv = document.createElement('div');
            dayDiv.className = 'heatmap-day';

            const dateYear = currentDate.getFullYear();
            const isInYear = dateYear === year;
            const isInFuture = currentDate > today;
            const isValidDate = isInYear && !isInFuture;

            if (isValidDate) {
                // Format date using local time（Avoid time zone issues）
                const year = currentDate.getFullYear();
                const month = String(currentDate.getMonth() + 1).padStart(2, '0');
                const day = String(currentDate.getDate()).padStart(2, '0');
                const dateStr = `${year}-${month}-${day}`;
                const minutes = data[dateStr] || 0;
                const level = getLevel(minutes);

                dayDiv.setAttribute('data-level', level);
                dayDiv.setAttribute('data-date', dateStr);

                // top two rows（Sunday and Monday）of tooltip Show down
                if (day <= 1) {
                    dayDiv.classList.add('tooltip-bottom');
                }

                // Format date display
                const displayDate = currentDate.toLocaleDateString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    weekday: 'short'
                });

                const tooltip = minutes > 0
                    ? `${displayDate}: ${formatMinutes(minutes)}`
                    : `${displayDate}: No reading history`;
                dayDiv.setAttribute('data-tooltip', tooltip);

                if (minutes > 0) {
                    totalActiveDays++;
                    totalYearMinutes += minutes;
                }
            } else {
                // Dates that are not in the current year or in the future are displayed as empty
                dayDiv.style.visibility = 'hidden';
            }

            weekDiv.appendChild(dayDiv);
            currentDate.setDate(currentDate.getDate() + 1);
        }

        grid.appendChild(weekDiv);
    }

    // Update total activity count
    const totalEl = document.getElementById('heatmap-total');
    if (totalEl) {
        const totalHours = Math.floor(totalYearMinutes / 60);
        const timeStr = totalHours > 0 ? `${totalHours}h` : `${totalYearMinutes}m`;
        totalEl.textContent = `Reading activities: ${totalActiveDays} days, total reading time ${timeStr}.`;
    }
}

// Rendering statistics cards
async function renderOverviewStats() {
    try {
        // Get the number of all papers
        let totalPapers = 0;
        try {
            const response = await fetch('/api/papers/all');
            if (response.ok) {
                const papers = await response.json();
                totalPapers = papers.length;
            }
        } catch (e) {
            console.error('Failed to get the number of papers:', e);
        }

        // Obtain daily reading data from the server to calculate the total reading time
        const historyData = getDailyReadingDataSync();
        const dailyData = getDailyReadingMinutes(historyData);

        // Calculate total reading time（minutes because dailyData Minutes are stored in）
        let totalMinutes = 0;
        Object.values(dailyData).forEach(minutes => {
            totalMinutes += (minutes || 0);
        });
        const totalHours = Math.floor(totalMinutes / 60);
        const remainingMinutes = totalMinutes % 60;

        // Calculate data for this week（From Monday to today）
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const dayOfWeek = today.getDay(); // 0 = Sunday, 1 = Monday, ..., 6 = Saturday
        const mondayOffset = dayOfWeek === 0 ? -6 : 1 - dayOfWeek; // If it’s Sunday, move forward6sky；Otherwise it will be pushed to Monday
        const monday = new Date(today);
        monday.setDate(today.getDate() + mondayOffset);

        let weekMinutes = 0;
        const weekDates = [];
        for (let i = 0; i <= dayOfWeek || (dayOfWeek === 0 && i <= 6); i++) {
            const date = new Date(monday);
            date.setDate(monday.getDate() + i);
            const dateStr = formatDateLocal(date);
            weekDates.push(dateStr);
            weekMinutes += (dailyData[dateStr] || 0);
        }

        const weekHours = Math.floor(weekMinutes / 60);
        const weekRemainingMinutes = weekMinutes % 60;

        // Count the number of papers read this week（Accurate calculation）
        let weekPapers = 0;
        try {
            const response = await fetch('/api/settings/reading-history/week-papers');
            if (response.ok) {
                const data = await response.json();
                if (data.success) {
                    weekPapers = data.count || 0;
                }
            }
        } catch (e) {
            console.error('Failed to get the number of papers read this week:', e);
            // ifAPIOn failure, use estimation method as fallback
            if (weekMinutes > 0) {
                const estimatedPapers = Math.round(weekMinutes / 45);
                const weekActiveDays = weekDates.filter(dateStr => dailyData[dateStr] && dailyData[dateStr] > 0).length;
                const maxPapers = weekActiveDays * 3;
                weekPapers = Math.max(1, Math.min(estimatedPapers, maxPapers));
            }
        }

        // Format this week's time display
        let weekTimeDisplay;
        if (weekHours > 0) {
            weekTimeDisplay = weekRemainingMinutes > 0 ? `${weekHours}h ${weekRemainingMinutes}m` : `${weekHours}h`;
        } else {
            weekTimeDisplay = `${weekMinutes}m`;
        }

        // Calculate the number of consecutive reading days
        const { currentStreak, bestStreak } = calculateStreaks(dailyData);

        // Format time display
        let timeDisplay;
        if (totalHours > 0) {
            timeDisplay = remainingMinutes > 0 ? `${totalHours}h ${remainingMinutes}m` : `${totalHours}h`;
        } else {
            timeDisplay = `${totalMinutes}m`;
        }

        // renew UI
        const totalPapersEl = document.getElementById('stat-total-papers');
        const totalTimeEl = document.getElementById('stat-total-time');
        const weekPapersEl = document.getElementById('stat-week-papers');
        const weekTimeEl = document.getElementById('stat-week-time');
        const currentStreakEl = document.getElementById('stat-current-streak');
        const bestStreakEl = document.getElementById('stat-best-streak');
        const userStatsEl = document.getElementById('setting-total-stats');

        if (totalPapersEl) totalPapersEl.textContent = totalPapers;
        if (totalTimeEl) totalTimeEl.textContent = timeDisplay;
        if (weekPapersEl) weekPapersEl.textContent = weekPapers;
        if (weekTimeEl) weekTimeEl.textContent = weekTimeDisplay;
        if (currentStreakEl) currentStreakEl.textContent = currentStreak;
        if (bestStreakEl) bestStreakEl.textContent = bestStreak;

        // User statistics summary
        const summaryHours = totalHours > 0 ? `${totalHours}h` : `${totalMinutes}m`;
        if (userStatsEl) userStatsEl.textContent = `${totalPapers} papers · ${summaryHours} read`;

        console.log('Statistics:', { totalPapers, totalMinutes, totalHours, currentStreak, bestStreak });

    } catch (e) {
        console.error('Failed to render statistics:', e);
    }
}

// Calculate the number of consecutive reading days
function calculateStreaks(dailyData) {
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    let currentStreak = 0;
    let bestStreak = 0;
    let tempStreak = 0;

    // Check back from today
    const checkDate = new Date(today);

    // Check if there are any readings today
    const todayStr = formatDateLocal(checkDate);
    if (dailyData[todayStr] && dailyData[todayStr] > 0) {
        currentStreak = 1;
        tempStreak = 1;
    }

    // Check back
    checkDate.setDate(checkDate.getDate() - 1);

    while (true) {
        const dateStr = formatDateLocal(checkDate);
        const hasReading = dailyData[dateStr] && dailyData[dateStr] > 0;

        if (hasReading) {
            tempStreak++;
            if (currentStreak > 0 || tempStreak === 1) {
                currentStreak = tempStreak;
            }
        } else {
            if (tempStreak > bestStreak) {
                bestStreak = tempStreak;
            }
            if (currentStreak > 0) {
                // Already broken, stop calculating the current continuous
                tempStreak = 0;
            } else {
                tempStreak = 0;
            }
        }

        checkDate.setDate(checkDate.getDate() - 1);

        // most checked 400 sky
        const daysDiff = Math.floor((today - checkDate) / (1000 * 60 * 60 * 24));
        if (daysDiff > 400) break;
    }

    if (tempStreak > bestStreak) {
        bestStreak = tempStreak;
    }
    if (currentStreak > bestStreak) {
        bestStreak = currentStreak;
    }

    return { currentStreak, bestStreak };
}

// Render recent reading activity
function renderRecentActivity() {
    const container = document.getElementById('recent-activity-list');
    if (!container) return;

    try {
        const key = 'recentPapers';
        const saved = localStorage.getItem(key);
        let recentItems = [];

        if (saved) {
            recentItems = JSON.parse(saved) || [];
        }

        // Take the nearest 5 strip
        const displayItems = recentItems.slice(0, 5);

        if (displayItems.length === 0) {
            container.innerHTML = `
                <div class="recent-empty">
                    <i class="fas fa-book-open"></i>
                    <p>No reading record yet</p>
                </div>
            `;
            return;
        }

        // Get paper information and render it
        Promise.all(displayItems.map(async item => {
            try {
                const response = await fetch(`/api/paper/${item.paperId}`);
                if (response.ok) {
                    const paper = await response.json();
                    return { ...item, paper };
                }
            } catch (e) {
                console.error('Failed to obtain paper information:', e);
            }
            return null;
        })).then(results => {
            const validResults = results.filter(r => r && r.paper);

            if (validResults.length === 0) {
                container.innerHTML = `
                    <div class="recent-empty">
                        <i class="fas fa-book-open"></i>
                        <p>No reading record yet</p>
                    </div>
                `;
                return;
            }

            container.innerHTML = validResults.map(item => {
                const paper = item.paper;
                const viewedAt = new Date(item.viewedAt);
                const timeAgo = getTimeAgo(viewedAt);
                // Calculate total reading time（PDF + AI Interpretation）
                const totalSeconds = (paper.read_time || 0) + (paper.analysis_view_time || 0);
                let readTimeDisplay = 'unread';
                if (totalSeconds > 0) {
                    const minutes = Math.floor(totalSeconds / 60);
                    const seconds = totalSeconds % 60;
                    if (minutes > 0) {
                        readTimeDisplay = seconds > 0 ? `Read ${minutes}m ${seconds}s` : `Read ${minutes}m`;
                    } else {
                        readTimeDisplay = `Read ${seconds}s`;
                    }
                }

                return `
                    <div class="recent-item" onclick="openPaperFromRecent('${paper.id}')">
                        <div class="recent-item-icon">
                            <i class="fas fa-file-pdf"></i>
                        </div>
                        <div class="recent-item-content">
                            <div class="recent-item-title">${escapeHtml(paper.title || paper.filename)}</div>
                            <div class="recent-item-meta">${readTimeDisplay}</div>
                        </div>
                        <div class="recent-item-time">${timeAgo}</div>
                    </div>
                `;
            }).join('');
        });

    } catch (e) {
        console.error('Rendering recent reads failed:', e);
        container.innerHTML = `
            <div class="recent-empty">
                <i class="fas fa-exclamation-circle"></i>
                <p>Loading failed</p>
            </div>
        `;
    }
}

// Calculate time difference display
function getTimeAgo(date) {
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMins < 1) return 'just';
    if (diffMins < 60) return `${diffMins} minutes ago`;
    if (diffHours < 24) return `${diffHours} hours ago`;
    if (diffDays < 7) return `${diffDays} days ago`;
    if (diffDays < 30) return `${Math.floor(diffDays / 7)} weeks ago`;
    return date.toLocaleDateString('en-US');
}

// Open paper from recent reading
function openPaperFromRecent(paperId) {
    switchTab('paper');
    // Open PDF reader
    window.open(`/viewer/${paperId}`, '_blank');
}

// ========== Habit set up (Keep compatible) ==========
function saveHabitSettings() {
    const countEl = document.getElementById('habit-recent-count');
    const count = countEl ? parseInt(countEl.value, 10) : 10;
    const settings = {
        recentCount: (!isNaN(count) && count > 0) ? count : 10
    };
    localStorage.setItem('habitSettings', JSON.stringify(settings));
    showMessage('Habit Settings saved', 'success');
    // Apply now
    renderRecentIfNoCategory();
}

function loadHabitSettings() {
    const saved = localStorage.getItem('habitSettings');
    let settings = { recentCount: 10 };
    if (saved) {
        try { settings = Object.assign(settings, JSON.parse(saved)); } catch { }
    }
    const input = document.getElementById('habit-recent-count');
    if (input) input.value = settings.recentCount;
}

function getHabitSettings() {
    const saved = localStorage.getItem('habitSettings');
    if (saved) {
        try { return JSON.parse(saved); } catch { }
    }
    return { recentCount: 10 };
}

// ========== Recently read ==========
function markPaperViewed(paperId) {
    try {
        const key = 'recentPapers';
        const now = Date.now();
        let items = [];
        const saved = localStorage.getItem(key);
        if (saved) { items = JSON.parse(saved) || []; }
        // Remove duplicates and keep the latest
        items = items.filter(it => it.paperId !== paperId);
        items.unshift({ paperId, viewedAt: now });
        // Limit maximum length（To avoid infinite growth, take 200）
        if (items.length > 200) items = items.slice(0, 200);
        localStorage.setItem(key, JSON.stringify(items));
    } catch (e) { console.error('Mark recent reading failed', e); }
}

// top task indicator
function updateTaskIndicator() {
    return;
}

function renderTaskTooltip() {
    const tooltip = document.getElementById('task-tooltip');
    if (!tooltip) return;
    const parts = [];
    // translate
    const tBlock = [];
    translationQueue.forEach(pid => {
        const p = (papers || []).find(x => x.id === pid) || {};
        tBlock.push(`<div class=\"tt-item\"><i class=\"fas fa-file-pdf\"></i><span>(queue)</span> ${escapeHtml(p.title || p.filename || pid)}</div>`);
    });
    Object.entries(translationStatus).forEach(([pid, s]) => {
        if (s.status === 'translating') {
            const p = (papers || []).find(x => x.id === pid) || {};
            tBlock.push(`<div class=\"tt-item\"><i class=\"fas fa-file-pdf\"></i><span>(implement)</span> ${escapeHtml(p.title || p.filename || pid)}</div>`);
        }
    });
    if (tBlock.length) {
        parts.push('<div class="tt-title">turn translate</div>');
        parts.push(`<div class=\"tt-group\">${tBlock.join('')}</div>`);
    }
    // Interpretation
    const aBlock = [];
    analysisQueue.forEach(pid => {
        const p = (papers || []).find(x => x.id === pid) || {};
        aBlock.push(`<div class=\"tt-item\"><i class=\"fas fa-file-pdf\"></i><span>(queue)</span> ${escapeHtml(p.title || p.filename || pid)}</div>`);
    });
    Object.entries(analysisStatus).forEach(([pid, s]) => {
        if (s.status === 'analyzing') {
            const p = (papers || []).find(x => x.id === pid) || {};
            aBlock.push(`<div class=\"tt-item\"><i class=\"fas fa-file-pdf\"></i><span>(implement)</span> ${escapeHtml(p.title || p.filename || pid)}</div>`);
        }
    });
    if (aBlock.length) {
        parts.push('<div class="tt-title">untie read</div>');
        parts.push(`<div class=\"tt-group\">${aBlock.join('')}</div>`);
    }
    tooltip.innerHTML = parts.length ? parts.join('') : '<div class="tt-item" style="color:#888;">No tasks in progress</div>';
}

// Show empty status（When no directory is selected）
function showEmptyState() {
    // Show to-be-read list by default instead of empty state
    showReadingList();
}

// Keep the old function name as an alias and display the to-be-read list by default
async function renderAllPapers() {
    await showReadingList();
}

async function renderRecentIfNoCategory() {
    await showReadingList();
}

// Refresh the list based on the current view mode（general function）
async function refreshCurrentViewList() {
    switch (currentViewMode) {
        case 'reading-list':
        case 'translating':
        case 'analyzing':
            await showReadingList();
            break;
        case 'category':
        default:
            if (currentCategoryId) {
                await loadPapers(currentCategoryId);
            } else {
                await renderAllPapers();
            }
            break;
    }
}

// Request translation
async function requestTranslation(paperId, event) {
    if (event) {
        event.stopPropagation();
    }
    const paper = papers.find(p => p.id === paperId);
    if (!paper) {
        showMessage('Paper not found', 'error');
        return;
    }

    // Check user's AI output language setting
    const userSettings = await getUserSettings();
    const aiLanguage = (userSettings && userSettings.aiLanguage) ? userSettings.aiLanguage : 'zh';

    // If AI output language is English, translation is not needed (papers are already in English)
    if (aiLanguage && aiLanguage.toLowerCase() === 'en') {
        showMessage('Current AI output language is English, and the paper is already in English. Translation is not needed.', 'warning');
        return;
    }

    // Check if there is a Chinese version
    if (paper.has_chinese_version) {
        if (confirm('This paper already has a Chinese version. Do you want to re-translate it?')) {
            // You can add re-translation logic here
        } else {
            return;
        }
    }

    // Check settings（use newAgenticUnified configuration）
    const settings = await getAgenticSettings();
    const llmCfg = getAgenticLLMConfig(settings, 'translate');
    if (!settings || !isAgenticLLMConfigured(llmCfg)) {
        showMessage('Please configure it in settings firstAIFunction parameters（LLM API）', 'warning');
        switchTab('setting');
        return;
    }

    // add to queue
    if (translationStatus[paperId]) {
        // This paper is already in the translation queue and will not be added again.
        return;
    }

    translationQueue.push(paperId);
    // Update queue position（Including the current one）
    const queuePosition = translationQueue.length;
    updateTranslationStatus(paperId, 'queued', queuePosition);
    saveQueuesToStorage(); // Save queue status
    renderPapersList(); // Update display now
    updateTaskIndicator();

    // Start processing the queue
    processTranslationQueue();
}

// Process translation queue（Globally unique queue to ensure that only one task is executed at the same time）
async function processTranslationQueue() {
    // Strict check: if it is being translated or the queue is empty, return directly
    if (isTranslating) {
        return; // There is already a task being executed and no new task will be started.
    }
    if (translationQueue.length === 0) {
        return; // Queue is empty
    }

    // Atomic setting: set the flag first, then get the task
    isTranslating = true;
    const paperId = translationQueue.shift();
    saveQueuesToStorage();

    try {
        updateTranslationStatus(paperId, 'translating', 0);
        renderPapersList(); // Update display

        const settings = await getTranslationSettings();
        const llmCfg = getAgenticLLMConfig(settings, 'translate');
        const response = await fetch('/api/paper/translate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                paper_id: paperId,
                openai_model: llmCfg.llmModel,
                openai_base_url: llmCfg.llmBaseUrl,
                openai_api_key: llmCfg.llmApiKey
            })
        });

        const result = await response.json();

        if (response.ok && result.success) {
            const taskId = result.task_id;

            // Start polling logs
            startLogPolling(taskId, paperId);

            // Update the status to Translating and savetaskId
            updateTranslationStatus(paperId, 'translating', 0, taskId);
            renderPapersList(); // Update display

            // Show log view button prompt
            // Do not display the startup prompt and the user can see the progress through the status bar
        } else {
            updateTranslationStatus(paperId, 'error', 0);
            saveQueuesToStorage();
            showMessage(result.error || 'Translation failed', 'error');
            isTranslating = false;
            renderPapersList(); // Update display
            processTranslationQueue(); // Continue processing the queue
        }
    } catch (error) {
        console.error('Translation failed:', error);
        updateTranslationStatus(paperId, 'error', 0);
        saveQueuesToStorage();
        showMessage('Translation failed, please try again later', 'error');
        isTranslating = false;
        renderPapersList(); // Update display
        processTranslationQueue(); // Continue processing the queue
    }
}

// Start polling translation logs
function startLogPolling(taskId, paperId) {
    // Stop previous polling（if there is）
    if (translationLogInterval[taskId]) {
        clearInterval(translationLogInterval[taskId]);
    }

    // Every2Poll once per second
    translationLogInterval[taskId] = setInterval(async () => {
        try {
            const response = await fetch(`/api/paper/translate/${taskId}/logs`);
            const result = await response.json();

            if (response.ok && result.success) {
                const status = result.status;
                const currentTaskId = translationStatus[paperId]?.taskId;
                const progressNum = Number.parseFloat(result.progress);
                const progressFromApi = Number.isFinite(progressNum) ? progressNum : null;
                const progressFromLogs = progressFromApi === null ? parseTranslationProgressFromLogs(result.logs) : null;
                const progress = progressFromApi !== null ? progressFromApi : (progressFromLogs ?? null);
                if (status === 'queued' || status === 'running') {
                    updateTranslationStatus(paperId, 'translating', 0, currentTaskId, progress);
                }

                // Stop polling if task completes or fails
                if (status === 'completed' || status === 'failed' || status === 'cancelled') {
                    clearInterval(translationLogInterval[taskId]);
                    delete translationLogInterval[taskId];

                    // update status（reservetaskId）
                    if (status === 'completed') {
                        updateTranslationStatus(paperId, 'completed', 0, currentTaskId);
                        const paper = papers.find(p => p.id === paperId);
                        if (paper && result.result && result.result.success) {
                            paper.has_chinese_version = true;
                            paper.chinese_version_path = result.result.chinese_version_path;
                        }
                        // When the translation is completed, the status column will be updated automatically.
                    } else {
                        updateTranslationStatus(paperId, 'error', 0, currentTaskId);
                        // Don't show error message when canceling
                        // exit code -15 yes SIGTERM, indicating that the user actively cancels and no error is displayed.
                        const errorMsg = result.result?.error || '';
                        const isCancelled = status === 'cancelled' || errorMsg.includes('-15') || errorMsg.includes('-9');
                        if (status === 'failed' && !isCancelled) {
                            showMessage(errorMsg || 'Translation failed', 'error');
                        }
                    }

                    // Continue processing the queue
                    isTranslating = false;
                    // Refresh the list based on the current view mode
                    await refreshCurrentViewList();
                    processTranslationQueue();
                }
            } else {
                // If the task does not exist（May be deleted externally or the server restarted）, stop polling and clean up the status
                if (response.status === 404) {
                    clearInterval(translationLogInterval[taskId]);
                    delete translationLogInterval[taskId];
                    // Remove from queue
                    const queueIndex = translationQueue.indexOf(paperId);
                    if (queueIndex !== -1) {
                        translationQueue.splice(queueIndex, 1);
                    }
                    // delete status
                    delete translationStatus[paperId];
                    // reset flag
                    isTranslating = false;
                    saveQueuesToStorage();
                    updateTaskIndicator();
                    // Refresh the list based on the current view mode
                    await refreshCurrentViewList();
                    processTranslationQueue();
                }
            }
        } catch (error) {
            console.error('Failed to obtain translation log:', error);
        }
    }, 2000); // Every2Poll once per second
}

// Stop log polling
function stopLogPolling(taskId) {
    if (translationLogInterval[taskId]) {
        clearInterval(translationLogInterval[taskId]);
        delete translationLogInterval[taskId];
    }
}

// View translation log
async function showTranslationLogs(paperId, event) {
    if (event) {
        event.stopPropagation();
    }
    const status = translationStatus[paperId];
    if (!status) {
        showMessage('Translation task not found', 'warning');
        return;
    }
    if (!status.taskId) {
        showLogModal('N/A', [], 'queued', paperId);
        return;
    }

    const taskId = status.taskId;

    // Get log
    try {
        const response = await fetch(`/api/paper/translate/${taskId}/logs`);
        const result = await response.json();

        if (response.ok && result.success) {
            // Show log modal box
            showLogModal(taskId, result.logs, result.status, paperId);
        } else {
            showMessage('Failed to get log', 'error');
        }
    } catch (error) {
        console.error('Failed to get log:', error);
        showMessage('Failed to get log', 'error');
    }
}

// Show log modal box
function showLogModal(taskId, logs, status, paperId) {
    const modalTitle = document.querySelector('#modal-title');
    const modalBody = document.querySelector('#modal-body');
    const confirmBtn = document.querySelector('#modal-confirm');
    const cancelBtn = document.querySelector('#modal-cancel');

    modalTitle.textContent = 'Translation log';

    const logContent = logs.length > 0 ? logs.join('\n') : 'No logs yet';
    const canCancel = status === 'running' || status === 'queued';

    modalBody.innerHTML = `
        <div style="margin-bottom: 15px;">
            <strong>state:</strong> 
            <span id="log-status">${getStatusText(status)}</span>
        </div>
        <div style="margin-bottom: 15px;">
            <button class="btn btn-secondary" onclick="refreshLogs('${taskId}', '${paperId}')" style="margin-right: 10px;">
                <i class="fas fa-refresh"></i> Refresh log
            </button>
            ${canCancel ? `
            <button class="btn btn-danger" onclick="cancelTranslation('${taskId}', '${paperId}')">
                <i class="fas fa-stop"></i> Terminate translation
            </button>
            ` : ''}
        </div>
        <div style="background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 4px; max-height: 500px; overflow-y: auto; font-family: 'Courier New', monospace; font-size: 12px; white-space: pre-wrap; word-wrap: break-word;">
            ${escapeHtml(logContent)}
        </div>
    `;

    confirmBtn.style.display = 'none';
    cancelBtn.textContent = 'closure';
    cancelBtn.onclick = () => hideModal();

    showModal();

    // If running, automatically refresh
    if (status === 'running' || status === 'queued') {
        const autoRefresh = setInterval(async () => {
            try {
                const response = await fetch(`/api/paper/translate/${taskId}/logs`);
                const result = await response.json();
                if (response.ok && result.success) {
                    const statusEl = document.getElementById('log-status');
                    if (statusEl) {
                        statusEl.textContent = getStatusText(result.status);
                    }
                    const logEl = modalBody.querySelector('div[style*="background: #1e1e1e"]');
                    if (logEl) {
                        logEl.textContent = result.logs.join('\n');
                    }

                    // If completed, stop automatic refresh
                    if (result.status === 'completed' || result.status === 'failed' || result.status === 'cancelled') {
                        clearInterval(autoRefresh);
                        // update status（reservetaskId）
                        const currentTaskId = translationStatus[paperId]?.taskId;
                        if (result.status === 'completed') {
                            updateTranslationStatus(paperId, 'completed', 0, currentTaskId);
                            const paper = papers.find(p => p.id === paperId);
                            if (paper && result.result && result.result.success) {
                                paper.has_chinese_version = true;
                                paper.chinese_version_path = result.result.chinese_version_path;
                            }
                        } else {
                            updateTranslationStatus(paperId, 'error', 0, currentTaskId);
                        }
                        renderPapersList();
                    }
                }
            } catch (error) {
                console.error('Failed to refresh log:', error);
            }
        }, 2000);

        // Stop automatic refresh when modal is closed
        const closeBtn = document.querySelector('.close');
        const originalClose = closeBtn.onclick;
        closeBtn.onclick = () => {
            clearInterval(autoRefresh);
            hideModal();
        };
    }
}

// Refresh log
async function refreshLogs(taskId, paperId) {
    showTranslationLogs(paperId);
}

// Cancel translation（Cancel from status, requiredtaskId）
async function cancelTranslation(taskId, paperId) {
    if (!confirm('Are you sure you want to terminate the translation?')) {
        return;
    }

    try {
        const response = await fetch(`/api/paper/translate/${taskId}/cancel`, {
            method: 'POST'
        });
        const result = await response.json();

        if (response.ok && result.success) {
            // The translation has been canceled and the status column will be updated automatically.
            stopLogPolling(taskId);
            updateTranslationStatus(paperId, 'error', 0, taskId);
            isTranslating = false;
            // Refresh the list based on the current view mode
            await refreshCurrentViewList();
            hideModal();
            processTranslationQueue(); // Continue processing the queue
        } else {
            // If the task does not exist（Server restart, etc.）, clean up the front-end status
            if (response.status === 404 || (result.error && result.error.includes('Task does not exist'))) {
                showMessage('The task does not exist and has been cleared', 'warning');
                // Check if translation is happening（Check before deleting status）
                const wasTranslating = isTranslating && translationStatus[paperId] && translationStatus[paperId].taskId === taskId;
                // Clean up frontend state
                stopLogPolling(taskId);
                // Remove from queue
                const queueIndex = translationQueue.indexOf(paperId);
                if (queueIndex !== -1) {
                    translationQueue.splice(queueIndex, 1);
                }
                // delete status
                delete translationStatus[paperId];
                // If translating, reset flag
                if (wasTranslating) {
                    isTranslating = false;
                }
                saveQueuesToStorage();
                updateTaskIndicator();
                // Refresh the list based on the current view mode
                await refreshCurrentViewList();
                hideModal();
                // Continue processing the queue
                processTranslationQueue();
            } else {
                showMessage(result.error || 'Cancel translation failed', 'error');
            }
        }
    } catch (error) {
        console.error('Cancel translation failed:', error);
        showMessage('Cancel translation failed', 'error');
    }
}

// Cancel translation from status（passpaperIdFindtaskId）
async function cancelTranslationFromStatus(paperId, event) {
    if (event) event.stopPropagation();
    const status = translationStatus[paperId];
    if (!status || !status.taskId) {
        showMessage('Translation task not found', 'warning');
        return;
    }
    await cancelTranslation(status.taskId, paperId);
}

// Cancel translation from queue
async function cancelTranslationFromQueue(paperId, event) {
    if (event) event.stopPropagation();
    const index = translationQueue.indexOf(paperId);
    if (index === -1) {
        showMessage('The paper is not in the queue', 'warning');
        return;
    }
    translationQueue.splice(index, 1);
    saveQueuesToStorage();
    delete translationStatus[paperId];
    updateTranslationStatus(paperId, 'error', 0);
    // Removed from queue, status column will update automatically
}

// Get status text
function getStatusText(status) {
    const statusMap = {
        'queued': 'in queue',
        'running': 'Translating',
        'completed': 'Completed',
        'failed': 'fail',
        'cancelled': 'Canceled'
    };
    return statusMap[status] || status;
}

// HTMLescape
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Update translation status
function updateTranslationStatus(paperId, status, queuePosition, taskId, progress) {
    // Keep what you havetaskId
    const existingTaskId = translationStatus[paperId]?.taskId;
    const existingProgress = translationStatus[paperId]?.progress;
    const nextProgress = Number.isFinite(progress)
        ? clampProgress(progress)
        : (Number.isFinite(existingProgress) ? clampProgress(existingProgress) : (status === 'queued' ? 0 : undefined));
    translationStatus[paperId] = {
        status: status,
        queuePosition: queuePosition,
        taskId: taskId || existingTaskId,  // Keep what you havetaskId, or use new
        progress: nextProgress,
    };

    // If completed or with error, remove from status
    if (status === 'completed' || status === 'error') {
        delete translationStatus[paperId];
    }

    // Update display（According to the current view mode）
    if (currentViewMode === 'reading-list') {
        // If you are viewing a to-read list, only update the status of a single paper without reloading the entire list
        updatePaperStatusDisplay(paperId);
    } else if (currentCategoryId) {
        updatePaperStatusDisplay(paperId);
    } else {
        renderRecentIfNoCategory();
    }
    updateTaskIndicator();
    saveQueuesToStorage();
}

// Get the total reading time display text
function getTotalReadTimeText(paper) {
    const readTime = paper.read_time || 0; // readPDFtime（Second）
    const analysisViewTime = paper.analysis_view_time || 0; // readAI Interpretation time（Second）
    const totalTime = readTime + analysisViewTime;

    if (totalTime === 0) {
        return '';
    }

    // Convert to minutes and seconds
    const minutes = Math.floor(totalTime / 60);
    const seconds = totalTime % 60;

    let timeText = '';
    if (minutes > 0) {
        timeText = `${minutes}m`;
        if (seconds > 0) {
            timeText += ` ${seconds}s`;
        }
    } else {
        timeText = `${seconds}s`;
    }

    return `<span style="color: #666; margin-left: 8px;">| Read: ${timeText}</span>`;
}

// Get the translation status display text
function getTranslationStatusText(paperId) {
    const status = translationStatus[paperId];
    if (!status) return '';

    if (status.status === 'translating') {
        const progress = clampProgress(status.progress ?? 0);
        return `<span class="translation-status translating">
            Translating ${Math.round(progress)}%
            <span class="progress-bar-container translation-status-bar"><span class="progress-bar" style="width: ${progress}%;"></span></span>
            <button class="status-cancel-btn" onclick="cancelTranslationFromStatus('${paperId}', event)" title="Cancel translation">
                <i class="fas fa-times"></i>
            </button>
        </span>`;
    } else if (status.status === 'queued') {
        // Calculate the current position in the queue
        const currentIndex = translationQueue.indexOf(paperId) + 1;
        return `<span class="translation-status queued">
            <i class="fas fa-clock"></i> in queue (${currentIndex}/${translationQueue.length})
            <button class="status-cancel-btn" onclick="cancelTranslationFromQueue('${paperId}', event)" title="Cancel queue">
                <i class="fas fa-times"></i>
            </button>
        </span>`;
    }
    return '';
}

function clampProgress(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) return 0;
    return Math.max(0, Math.min(100, n));
}

function extractTranslationProgressFromText(text) {
    if (!text) return null;
    const percentMatches = [...String(text).matchAll(/(\d{1,3})(?:\.\d+)?\s*%/g)].map(m => Number(m[1]));
    if (percentMatches.length > 0) {
        return clampProgress(percentMatches[percentMatches.length - 1]);
    }
    const pageFraction = String(text).match(/\bpages?\b\D{0,20}(\d+)\s*\/\s*(\d+)\b/i);
    if (pageFraction) {
        const cur = Number(pageFraction[1]);
        const total = Number(pageFraction[2]);
        if (Number.isFinite(cur) && Number.isFinite(total) && total > 0) {
            return clampProgress(Math.floor((cur * 100) / total));
        }
    }
    const ofFraction = String(text).match(/\bpages?\b\D{0,20}(\d+)\s+of\s+(\d+)\b/i);
    if (ofFraction) {
        const cur = Number(ofFraction[1]);
        const total = Number(ofFraction[2]);
        if (Number.isFinite(cur) && Number.isFinite(total) && total > 0) {
            return clampProgress(Math.floor((cur * 100) / total));
        }
    }
    const genericFraction = String(text).match(/(?<!\d)(\d{1,5})\s*\/\s*(\d{1,5})(?!\d)/);
    if (genericFraction) {
        const cur = Number(genericFraction[1]);
        const total = Number(genericFraction[2]);
        if (Number.isFinite(cur) && Number.isFinite(total) && total > 0 && total >= cur) {
            return clampProgress(Math.floor((cur * 100) / total));
        }
    }
    return null;
}

function parseTranslationProgressFromLogs(logs) {
    if (!Array.isArray(logs) || logs.length === 0) return null;
    for (let i = logs.length - 1; i >= 0; i--) {
        const progress = extractTranslationProgressFromText(logs[i]);
        if (progress !== null) return progress;
    }
    return null;
}

// Open Chinese versionPDF
function openChineseVersion(paperId) {
    const paper = papers.find(p => p.id === paperId);
    if (!paper || !paper.has_chinese_version) {
        showMessage('Chinese version does not exist', 'error');
        return;
    }
    const viewerUrl = `/viewer/${paperId}?chinese=true`;
    window.open(viewerUrl, '_blank');
    markPaperViewed(paperId);
}

// ========== AIInterpret related functions（Deprecated, useAgenticUnified configuration）==========

// Save interpretation settings（Deprecated）
async function saveAnalysisSettings() {
    console.warn('saveAnalysisSettings is deprecated, use saveAgenticSettings instead');
    return saveAgenticSettings();
}

// Load interpretation settings（Deprecated）
async function loadAnalysisSettings() {
    console.warn('loadAnalysisSettings is deprecated, use loadAgenticSettings instead');
    return loadAgenticSettings();
}

// Get interpretation settings（Deprecated）
async function getAnalysisSettings() {
    console.warn('getAnalysisSettings is deprecated, use getAgenticSettings instead');
    return getAgenticSettings();
}

// ========== Zotero Import related functions ==========

// Import status
let importEventSource = null;
let importInProgress = false;
let currentImportTaskId = null;

// Initialize import function
async function initImportFeature() {
    // Initialize import type tab switching
    const importTypeTabs = document.querySelectorAll('.import-type-tab');
    importTypeTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const importType = tab.getAttribute('data-import-type');
            switchImportType(importType);
        });
    });

    // initialization Zotero import
    const dropZone = document.getElementById('import-drop-zone');
    const fileInput = document.getElementById('rdf-file-input');

    if (!dropZone || !fileInput) return;

    // drag event
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.add('drag-over');
    });

    dropZone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove('drag-over');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove('drag-over');

        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleRdfFile(files[0]);
        }
    });

    // Click to upload
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleRdfFile(e.target.files[0]);
        }
    });

    // Populate target directory selection list（Get the latest data）
    await populateImportTargetCategories();

    // Check if there are any import tasks in progress（Restore after page refresh）
    checkExistingImportTask();

    // Initialize import from export file
    initExportFileImport();

    console.log('Import Function initialization completed');
}

// Switch import type
function switchImportType(type) {
    // Update tab status
    document.querySelectorAll('.import-type-tab').forEach(tab => {
        tab.classList.remove('active');
        if (tab.getAttribute('data-import-type') === type) {
            tab.classList.add('active');
        }
    });

    // Switch panel display
    const zoteroPanel = document.getElementById('import-zotero-panel');
    const exportPanel = document.getElementById('import-export-panel');

    if (type === 'zotero') {
        zoteroPanel.style.display = 'block';
        exportPanel.style.display = 'none';
    } else if (type === 'export') {
        zoteroPanel.style.display = 'none';
        exportPanel.style.display = 'block';
    }
}

// Initialize import from export file
function initExportFileImport() {
    const dropZone = document.getElementById('export-import-drop-zone');
    const fileInput = document.getElementById('export-file-input');

    if (!dropZone || !fileInput) return;

    // drag event
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.add('drag-over');
    });

    dropZone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove('drag-over');
    });

    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropZone.classList.remove('drag-over');

        const files = e.dataTransfer.files;
        if (files.length > 0) {
            handleExportZipFile(files[0]);
        }
    });

    // Click to upload
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleExportZipFile(e.target.files[0]);
        }
    });
}

// Handle export ZIP document
async function handleExportZipFile(file) {
    if (!file.name.toLowerCase().endsWith('.zip')) {
        showMessage('Please select ZIP document', 'error');
        return;
    }

    const dropZone = document.getElementById('export-import-drop-zone');
    const dropZoneContent = document.getElementById('export-drop-zone-content');
    const progressContainer = document.getElementById('export-import-progress-container');

    // Hide the contents of the drag area and show the progress
    if (dropZoneContent) dropZoneContent.style.display = 'none';
    progressContainer.style.display = 'block';

    // reset progress
    updateExportImportProgress({
        status: 'uploading',
        progress: 0,
        current: 0,
        total: 0,
        message: 'Uploading file...',
        success_count: 0,
        failed_count: 0,
        skipped_count: 0,
        duplicate_count: 0,
    });

    // use XMLHttpRequest to support upload progress
    const formData = new FormData();
    formData.append('file', file);

    const xhr = new XMLHttpRequest();

    // Monitor upload progress
    xhr.upload.addEventListener('progress', (e) => {
        if (e.lengthComputable) {
            const percentComplete = Math.round((e.loaded / e.total) * 100);
            updateExportImportProgress({
                status: 'uploading',
                progress: percentComplete,
                current: e.loaded,
                total: e.total,
                message: `Uploading file... ${percentComplete}%`,
                success_count: 0,
                failed_count: 0,
                skipped_count: 0,
                duplicate_count: 0,
            });
        }
    });

    // Monitor upload completion
    xhr.addEventListener('load', () => {
        if (xhr.status === 200) {
            try {
                const data = JSON.parse(xhr.responseText);

                if (!data.success) {
                    showMessage(data.error || 'Import failed', 'error');
                    if (dropZoneContent) dropZoneContent.style.display = 'flex';
                    progressContainer.style.display = 'none';
                    return;
                }

                // Upload completed, start processing
                updateExportImportProgress({
                    status: 'processing',
                    progress: 100,
                    current: 0,
                    total: 0,
                    message: 'File upload is completed, start decompressing and importing...',
                    success_count: 0,
                    failed_count: 0,
                    skipped_count: 0,
                    duplicate_count: 0,
                });

                // Start monitoring the import progress
                const taskId = data.task_id;
                startExportImportProgressStream(taskId);

                showMessage('Import task started', 'success');

            } catch (error) {
                console.error('Failed to parse response:', error);
                showMessage('Import failed: ' + error.message, 'error');
                if (dropZoneContent) dropZoneContent.style.display = 'flex';
                progressContainer.style.display = 'none';
            }
        } else {
            showMessage(`Upload failed: HTTP ${xhr.status}`, 'error');
            if (dropZoneContent) dropZoneContent.style.display = 'flex';
            progressContainer.style.display = 'none';
        }
    });

    // Monitor upload errors
    xhr.addEventListener('error', () => {
        showMessage('Upload failed: network error', 'error');
        if (dropZoneContent) dropZoneContent.style.display = 'flex';
        progressContainer.style.display = 'none';
    });

    // Monitor upload cancellation
    xhr.addEventListener('abort', () => {
        showMessage('Upload canceled', 'error');
        if (dropZoneContent) dropZoneContent.style.display = 'flex';
        progressContainer.style.display = 'none';
    });

    // Send request
    xhr.open('POST', '/api/import/from-export');
    xhr.send(formData);
}

// Start monitoring the export file import progress（SSE）
function startExportImportProgressStream(taskId) {
    let exportImportEventSource = new EventSource(`/api/import/zotero/progress/${taskId}`);

    exportImportEventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            updateExportImportProgress(data);

            // If completed or failed, close the connection
            if (data.status === 'completed' || data.status === 'error') {
                exportImportEventSource.close();

                // Make sure to turn off loading status
                showLoading(false);

                // Reset now UI, remove progress display
                const dropZoneContent = document.getElementById('export-drop-zone-content');
                const progressContainer = document.getElementById('export-import-progress-container');
                if (dropZoneContent) dropZoneContent.style.display = 'flex';
                if (progressContainer) progressContainer.style.display = 'none';

                // Silently refresh the classification tree（Do not show loading status）
                loadCategories(true).catch(err => {
                    console.error('Failed to refresh classification tree:', err);
                });
            }
        } catch (e) {
            console.error('Failed to parse progress data:', e);
        }
    };

    exportImportEventSource.onerror = (e) => {
        console.error('SSE Connection error:', e);
        if (exportImportEventSource) {
            exportImportEventSource.close();
        }
    };
}

// Update export file import progress
function updateExportImportProgress(data) {
    const { status, progress, current, total, message, success_count, failed_count, skipped_count, duplicate_count } = data;

    const statusText = document.getElementById('export-import-status-text');
    const progressPercent = document.getElementById('export-import-progress-percent');
    const progressFill = document.getElementById('export-import-progress-fill');
    const currentItem = document.getElementById('export-import-current-item');
    const successCountEl = document.getElementById('export-import-success-count');
    const failedCountEl = document.getElementById('export-import-failed-count');
    const skippedCountEl = document.getElementById('export-import-skipped-count');
    const duplicateCountEl = document.getElementById('export-import-duplicate-count');

    if (status === 'parsing' || status === 'uploading') {
        statusText.textContent = message || 'Processing...';
        progressPercent.textContent = '0%';
        progressFill.style.width = '0%';
    } else if (status === 'importing') {
        statusText.textContent = 'Importing paper...';
        const percent = total > 0 ? Math.round((current / total) * 100) : 0;
        progressPercent.textContent = `${percent}%`;
        progressFill.style.width = percent + '%';
        currentItem.textContent = message || '';
    } else if (status === 'completed') {
        statusText.textContent = 'Import completed!';
        statusText.style.color = '#2da44e';
        progressPercent.textContent = '100%';
        progressFill.style.width = '100%';
        currentItem.textContent = `Imported successfully ${success_count} papers`;
        currentItem.style.color = '#2da44e';
    } else if (status === 'error') {
        statusText.textContent = 'Import failed';
        statusText.style.color = '#d73a49';
        currentItem.textContent = message || 'unknown error';
        currentItem.style.color = '#d73a49';
    }

    // update count
    if (successCountEl) successCountEl.textContent = success_count || 0;
    if (failedCountEl) failedCountEl.textContent = failed_count || 0;
    if (skippedCountEl) skippedCountEl.textContent = skipped_count || 0;
    if (duplicateCountEl) duplicateCountEl.textContent = duplicate_count || 0;
}

// Populate the import target directory selection list（Get the latest directory data asynchronously）
async function populateImportTargetCategories() {
    const select = document.getElementById('import-target-category');
    if (!select) return;

    // Keep the currently selected value
    const currentValue = select.value;

    // Keep default options
    select.innerHTML = '<option value="">root directory（default）</option>';

    try {
        // from API Get the latest directory data
        const response = await fetch('/api/categories');
        const latestCategories = await response.json();

        // Add directory options recursively
        function addCategoryOptions(node, level = 0) {
            if (!node.children) return;

            node.children.forEach(child => {
                const indent = '　'.repeat(level); // Use full-width spaces for indentation
                const option = document.createElement('option');
                option.value = child.id;
                option.textContent = `${indent}📁 ${child.name}`;
                select.appendChild(option);

                // Add subdirectories recursively
                if (child.children && child.children.length > 0) {
                    addCategoryOptions(child, level + 1);
                }
            });
        }

        addCategoryOptions(latestCategories);

        // Restore previously selected value（if it still exists）
        if (currentValue) {
            const optionExists = Array.from(select.options).some(opt => opt.value === currentValue);
            if (optionExists) {
                select.value = currentValue;
            }
        }

        // Update global variables at the same time to maintain consistency
        categories = latestCategories;
    } catch (error) {
        console.error('Failed to get directory data:', error);
        // If retrieval fails, use global variables as fallback
        function addCategoryOptions(node, level = 0) {
            if (!node.children) return;

            node.children.forEach(child => {
                const indent = '　'.repeat(level);
                const option = document.createElement('option');
                option.value = child.id;
                option.textContent = `${indent}📁 ${child.name}`;
                select.appendChild(option);

                if (child.children && child.children.length > 0) {
                    addCategoryOptions(child, level + 1);
                }
            });
        }
        addCategoryOptions(categories);
    }
}

// Check if there are any import tasks in progress
async function checkExistingImportTask() {
    try {
        const response = await fetch('/api/import/zotero/status');
        const data = await response.json();

        if (data.has_task && data.status !== 'completed' && data.status !== 'error') {
            console.log('Discover ongoing import tasks:', data.task_id);
            importInProgress = true;

            // Show progress interface
            document.getElementById('drop-zone-content').style.display = 'none';
            document.getElementById('import-progress-container').style.display = 'block';
            document.getElementById('import-result').style.display = 'none';

            // Update current progress
            updateImportStatus(
                `Importing paper (${data.current}/${data.total})...`,
                data.progress,
                data.message || 'Processing...'
            );

            // Reconnect SSE
            currentImportTaskId = data.task_id;
            startImportProgressStream(data.task_id);
        } else if (data.has_task && data.status === 'completed') {
            // The task has been completed. Reset the interface directly without displaying the results.
            importInProgress = false;
            currentImportTaskId = null;
            showLoading(false);

            const dropZoneContent = document.getElementById('drop-zone-content');
            const progressContainer = document.getElementById('import-progress-container');
            const importResult = document.getElementById('import-result');

            if (dropZoneContent) dropZoneContent.style.display = 'flex';
            if (progressContainer) progressContainer.style.display = 'none';
            if (importResult) importResult.style.display = 'none';

            // Show success message
            const msg = `Import completed! success ${data.success_count || 0} Chapter`;
            showMessage(msg, 'success');

            // Silently refresh the classification tree（Do not show loading status）
            loadCategories(true).catch(err => {
                console.error('Failed to refresh classification tree:', err);
            });
        }
    } catch (e) {
        console.log('Checking import task status failed:', e);
    }
}

// deal with RDF File upload
async function handleRdfFile(file) {
    if (!file.name.toLowerCase().endsWith('.rdf')) {
        showMessage('Please upload .rdf format file', 'error');
        return;
    }

    if (importInProgress) {
        showMessage('Importing, please wait for completion', 'warning');
        return;
    }

    importInProgress = true;

    // Hide upload area and show progress
    document.getElementById('drop-zone-content').style.display = 'none';
    document.getElementById('import-progress-container').style.display = 'block';
    document.getElementById('import-result').style.display = 'none';

    updateImportStatus('Uploading RDF document...', 0, 'In preparation...');

    // Get target directory
    const targetCategoryId = document.getElementById('import-target-category')?.value || '';

    // Upload files
    const formData = new FormData();
    formData.append('file', file);
    formData.append('target_category_id', targetCategoryId);

    try {
        const response = await fetch('/api/import/zotero', {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Upload failed');
        }

        const result = await response.json();

        if (result.success) {
            // If there is information about restoring the import, a prompt will be displayed.
            if (result.already_imported > 0) {
                showMessage(
                    `detected ${result.already_imported} papers have been imported and will be ${result.already_imported + 1} Chapter starts and continues importing`,
                    'info'
                );
            }

            // Start monitoring the import progress
            startImportProgressStream(result.task_id);
        } else {
            // If all papers have been imported, display a special prompt
            if (result.already_imported && result.original_total && result.already_imported === result.original_total) {
                showMessage('All papers have been imported, no need to import again', 'info');
                resetImport();
            } else {
                throw new Error(result.error || 'Import failed');
            }
        }
    } catch (error) {
        console.error('Import failed:', error);
        showMessage('Import failed: ' + error.message, 'error');
        resetImport();
    }
}

// Start monitoring the import progress（SSE）
function startImportProgressStream(taskId) {
    if (importEventSource) {
        importEventSource.close();
    }

    currentImportTaskId = taskId;

    // The cancel button is hidden and will not be shown again
    // const cancelBtn = document.getElementById('cancel-import-btn');
    // if (cancelBtn) {
    //     cancelBtn.style.display = 'inline-block';
    // }

    importEventSource = new EventSource(`/api/import/zotero/progress/${taskId}`);

    importEventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleImportProgress(data);
        } catch (e) {
            console.error('Failed to parse progress data:', e);
        }
    };

    importEventSource.onerror = (e) => {
        console.error('SSE Connection error:', e);
        if (importEventSource) {
            importEventSource.close();
            importEventSource = null;
        }
    };
}

// Handling import progress updates
let lastRefreshTime = 0;
const REFRESH_INTERVAL = 3000; // Every3Refresh the paper list once every second

function handleImportProgress(data) {
    const { status, progress, current, total, message, success_count, failed_count, skipped_count, duplicate_count, others_count, original_total, already_imported_count } = data;

    if (status === 'parsing') {
        updateImportStatus('Parsing RDF document...', 0, message || 'Obtaining paper information...');
    } else if (status === 'importing') {
        const percent = total > 0 ? Math.round((current / total) * 100) : 0;
        let statusText = `Importing paper (${current}/${total})...`;
        let detailText = message || `Processing...`;

        // If there is information about restoring the import, it will be displayed in the details.
        if (already_imported_count > 0 && original_total) {
            const actualCurrent = already_imported_count + current;
            statusText = `Importing paper (${actualCurrent}/${original_total})...`;
            if (!message || !message.includes('Imported')) {
                detailText = `skipped ${already_imported_count} imported papers,${message || 'Processing...'}`;
            }
        }

        updateImportStatus(
            statusText,
            percent,
            detailText
        );

        // Regularly refresh the paper list（If you are currently on the home page）
        const now = Date.now();
        if (now - lastRefreshTime > REFRESH_INTERVAL) {
            lastRefreshTime = now;
            // If you are currently in category view, refresh the paper list
            if (currentCategoryId) {
                loadPapers(currentCategoryId).catch(err => {
                    console.error('Failed to refresh paper list:', err);
                });
            }
        }
    } else if (status === 'cancelled' || status === 'cancelling') {
        // Import canceled
        if (importEventSource) {
            importEventSource.close();
            importEventSource = null;
        }
        importInProgress = false;
        currentImportTaskId = null;

        // Hide cancel button
        const cancelBtn = document.getElementById('cancel-import-btn');
        if (cancelBtn) {
            cancelBtn.style.display = 'none';
        }

        // Update status display
        updateImportStatus('Import canceled', progress || 0, message || 'Import task canceled');

        // Remove all loading status
        showLoading(false);

        // Show cancellation message
        showMessage('Import canceled', 'warning');

        // Reset interface after delay
        setTimeout(() => {
            resetImport();
        }, 2000);
    } else if (status === 'completed') {
        // Import completed
        if (importEventSource) {
            importEventSource.close();
            importEventSource = null;
        }
        importInProgress = false;
        currentImportTaskId = null;

        // Hide cancel button
        const cancelBtn = document.getElementById('cancel-import-btn');
        if (cancelBtn) {
            cancelBtn.style.display = 'none';
        }

        // Remove all loading status
        showLoading(false);

        // Directly hide all import-relatedUI, return to normal state
        const dropZoneContent = document.getElementById('drop-zone-content');
        const progressContainer = document.getElementById('import-progress-container');
        const importResult = document.getElementById('import-result');

        if (dropZoneContent) dropZoneContent.style.display = 'flex';
        if (progressContainer) progressContainer.style.display = 'none';
        if (importResult) importResult.style.display = 'none';

        // Reset file input
        const fileInput = document.getElementById('rdf-file-input');
        if (fileInput) fileInput.value = '';

        // Silently refresh the classification tree（Do not show loading status）
        loadCategories(true).catch(err => {
            console.error('Failed to refresh classification tree:', err);
        });

        // If you are currently in category view, refresh the paper list
        if (currentCategoryId) {
            loadPapers(currentCategoryId).catch(err => {
                console.error('Failed to refresh paper list:', err);
            });
        }
    } else if (status === 'error') {
        if (importEventSource) {
            importEventSource.close();
            importEventSource = null;
        }
        importInProgress = false;
        currentImportTaskId = null;

        // Hide cancel button
        const cancelBtn = document.getElementById('cancel-import-btn');
        if (cancelBtn) {
            cancelBtn.style.display = 'none';
        }

        // Remove loading status
        showLoading(false);
        showMessage('Import failed: ' + (message || 'unknown error'), 'error');
        resetImport();
    }
}

// Cancel import
async function cancelImport() {
    if (!currentImportTaskId) {
        showMessage('There are no import tasks in progress', 'warning');
        return;
    }

    const cancelBtn = document.getElementById('cancel-import-btn');
    if (cancelBtn) {
        cancelBtn.disabled = true;
        cancelBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Canceling...';
    }

    try {
        const response = await fetch(`/api/import/zotero/cancel/${currentImportTaskId}`, {
            method: 'POST'
        });

        const result = await response.json();

        if (result.success) {
            showMessage('Canceling import...', 'info');
        } else {
            showMessage('Cancellation failed: ' + (result.error || 'unknown error'), 'error');
            if (cancelBtn) {
                cancelBtn.disabled = false;
                cancelBtn.innerHTML = '<i class="fas fa-times"></i> Cancel import';
            }
        }
    } catch (error) {
        console.error('Unable to cancel import:', error);
        showMessage('Unable to cancel import: ' + error.message, 'error');
        if (cancelBtn) {
            cancelBtn.disabled = false;
            cancelBtn.innerHTML = '<i class="fas fa-times"></i> Cancel import';
        }
    }
}

// Update import status display
function updateImportStatus(statusText, percent, detail) {
    const statusTextEl = document.getElementById('import-status-text');
    const progressFill = document.getElementById('import-progress-fill');
    const progressDetail = document.getElementById('import-progress-detail');

    if (statusTextEl) statusTextEl.textContent = statusText;
    if (progressFill) progressFill.style.width = percent + '%';
    if (progressDetail) progressDetail.textContent = detail;
}

// Show import results（Deprecated. After the import is completed, the interface will be reset directly without displaying the results.）
function showImportResult(successCount, failedCount, skippedCount, duplicateCount = 0, othersCount = 0) {
    // No longer display the results interface, reset directly
    importInProgress = false;
    currentImportTaskId = null;
    showLoading(false);

    const dropZoneContent = document.getElementById('drop-zone-content');
    const progressContainer = document.getElementById('import-progress-container');
    const importResult = document.getElementById('import-result');

    if (dropZoneContent) dropZoneContent.style.display = 'flex';
    if (progressContainer) progressContainer.style.display = 'none';
    if (importResult) importResult.style.display = 'none';

    // Show success message
    let msg = `Import completed! success ${successCount} Chapter`;
    if (failedCount > 0) msg += `,fail ${failedCount} Chapter`;
    if (skippedCount > 0) msg += `,jump over ${skippedCount} Chapter`;
    if (duplicateCount > 0) msg += `,repeat ${duplicateCount} Chapter`;
    showMessage(msg, 'success');
}

// Reset import interface
function resetImport() {
    importInProgress = false;
    currentImportTaskId = null;

    if (importEventSource) {
        importEventSource.close();
        importEventSource = null;
    }

    // Hide cancel button
    const cancelBtn = document.getElementById('cancel-import-btn');
    if (cancelBtn) {
        cancelBtn.style.display = 'none';
        cancelBtn.disabled = false;
        cancelBtn.innerHTML = '<i class="fas fa-times"></i> Cancel import';
    }

    document.getElementById('drop-zone-content').style.display = 'flex';
    document.getElementById('import-progress-container').style.display = 'none';
    document.getElementById('import-result').style.display = 'none';

    // Reset file input
    const fileInput = document.getElementById('rdf-file-input');
    if (fileInput) fileInput.value = '';
}

// switch to specified setting panel
async function switchSettingPanel(panelName) {
    document.querySelectorAll('.setting-nav-item').forEach(b => b.classList.remove('active'));
    const targetBtn = document.querySelector(`.setting-nav-item[data-setting="${panelName}"]`);
    if (targetBtn) targetBtn.classList.add('active');

    document.querySelectorAll('.setting-panel').forEach(p => p.style.display = 'none');
    const targetPanel = document.getElementById(`setting-panel-${panelName}`);
    if (targetPanel) targetPanel.style.display = 'block';

    // If you switch to Import Panel, refresh directory selection list（Get the latest data）
    if (panelName === 'import') {
        await populateImportTargetCategories();
    }

    // If you switch to Export panel, reset UI
    if (panelName === 'export') {
        resetExportUI();
        await loadPapersDir();
    }

    // If you switch to Daily arXiv Panel, load settings
    if (panelName === 'daily-arxiv') {
        await loadDailyArxivSettings();
        const maxKeywordsInput = document.getElementById('daily-arxiv-max-keywords');
        if (maxKeywordsInput) {
            maxKeywordsInput.value = dailyArxivSettings.maxKeywords || 1;
        }
        // Bind the enter event of the keyword input box
        setupDailyArxivKeywordInput();
    }

    // save state
    saveCurrentViewState();
}

// Switch to overview page
function switchToOverview() {
    switchSettingPanel('overview');
}

// Restore ongoing task status（Page refresh/After reopening）
async function restoreActiveTasks() {
    try {
        // First restore the queuing status from the local queue（These queues may not have been submitted to the backend before being flushed）
        const queuedTranslateIds = Array.isArray(translationQueue) ? [...translationQueue] : [];
        const queuedAnalyzeIds = Array.isArray(analysisQueue) ? [...analysisQueue] : [];

        translationStatus = {};
        analysisStatus = {};

        queuedTranslateIds.forEach((pid) => {
            translationStatus[pid] = { status: 'queued', taskId: translationStatus[pid]?.taskId || null };
        });
        queuedAnalyzeIds.forEach((pid) => {
            analysisStatus[pid] = { status: 'queued', taskId: analysisStatus[pid]?.taskId || null };
        });

        // Translation tasks（Merge active tasks from backend）
        const tRes = await fetch('/api/paper/translate/active');
        const tJson = await tRes.json();
        if (tRes.ok && tJson.success && Array.isArray(tJson.tasks)) {
            let hasRunningTranslation = false;
            for (const t of tJson.tasks) {
                const paperId = t.paper_id;
                try {
                    const logRes = await fetch(`/api/paper/translate/${t.task_id}/logs`);
                    if (logRes.ok) {
                        const logData = await logRes.json();
                        if (logData.success && (logData.status === 'running' || logData.status === 'queued')) {
                            translationStatus[paperId] = {
                                status: t.status === 'running' ? 'translating' : 'queued',
                                taskId: t.task_id,
                            };
                            if (t.status === 'queued' && !translationQueue.includes(paperId)) {
                                translationQueue.push(paperId);
                            }
                            if (t.status === 'running') {
                                hasRunningTranslation = true;
                                startLogPolling(t.task_id, paperId);
                            }
                        }
                    }
                } catch (e) {
                    console.error(`Verify translation tasks ${t.task_id} fail:`, e);
                }
            }
            isTranslating = hasRunningTranslation;
        }

        // Interpretation tasks（Merge active tasks from backend）
        const aRes = await fetch('/api/paper/analyze/active');
        const aJson = await aRes.json();
        if (aRes.ok && aJson.success && Array.isArray(aJson.tasks)) {
            let hasRunningAnalysis = false;
            for (const a of aJson.tasks) {
                const paperId = a.paper_id;
                try {
                    const logRes = await fetch(`/api/paper/analyze/${a.task_id}/logs`);
                    if (logRes.ok) {
                        const logData = await logRes.json();
                        if (logData.success && (logData.status === 'running' || logData.status === 'queued')) {
                            analysisStatus[paperId] = {
                                status: a.status === 'running' ? 'analyzing' : 'queued',
                                taskId: a.task_id,
                                step: a.step || null,
                            };
                            if (a.status === 'queued' && !analysisQueue.includes(paperId)) {
                                analysisQueue.push(paperId);
                            }
                            if (a.status === 'running') {
                                hasRunningAnalysis = true;
                                startAnalysisLogPolling(a.task_id, paperId);
                            }
                        }
                    }
                } catch (e) {
                    console.error(`Validate interpretation tasks ${a.task_id} fail:`, e);
                }
            }
            isAnalyzing = hasRunningAnalysis;
        }

        // Persist and update indicators
        saveQueuesToStorage();
        updateTaskIndicator();
        // Note: Do not refresh the view here, by restoreViewState Unified processing
    } catch (e) {
        console.error('Failed to restore task status:', e);
    }
}

// askAI Interpretation
async function requestAnalysis(paperId, event) {
    if (event) {
        event.stopPropagation();
    }

    const paper = papers.find(p => p.id === paperId);
    if (!paper) {
        showMessage('Paper not found', 'error');
        return;
    }

    // Check if interpretation results already exist
    const hasResult = paper.has_analysis_result;
    if (hasResult) {
        if (!confirm('This paper already has an AI Interpretation, reinterpret?')) {
            return;
        }
    }

    // Check settings（use newAgenticUnified configuration）
    const settings = await getAgenticSettings();

    if (!settings) {
        showMessage('Please configure it in settings firstAIFunction parameters（LLM APIandMinerU）', 'warning');
        // Switch to settings page
        document.querySelector('.nav-tab[data-tab="setting"]').click();
        return;
    }

    // Check MinerU configuration based on mode
    const useApi = settings.mineruUseApi === true;
    const mineruConfigured = useApi
        ? (settings.mineruApiToken && settings.mineruApiToken.trim() !== '')
        : (settings.mineruServerUrl && settings.mineruServerUrl.trim() !== '');

    const llmCfg = getAgenticLLMConfig(settings, 'interpret');
    if (!mineruConfigured || !isAgenticLLMConfigured(llmCfg)) {
        showMessage('Please configure it in settings firstAIFunction parameters（LLM APIandMinerU）', 'warning');
        // Switch to settings page
        document.querySelector('.nav-tab[data-tab="setting"]').click();
        return;
    }
    // Notice:systemPrompt Can be empty, use default value

    // Check if already in queue or being interpreted
    if (analysisStatus[paperId]) {
        const status = analysisStatus[paperId].status;
        if (status === 'analyzing' || status === 'queued') {
            // This paper is already in the interpretation queue and will not be added again.
            return;
        }
    }

    // add to queue
    analysisQueue.push(paperId);

    // update status
    const queuePosition = analysisQueue.length;
    updateAnalysisStatus(paperId, 'queued', queuePosition);
    saveQueuesToStorage();

    // Update display now（According to the current view mode）
    if (currentViewMode === 'reading-list') {
        // Only the status of a single paper is updated in the to-read list, and the entire list is not refreshed.
        updatePaperStatusDisplay(paperId);
    } else if (currentCategoryId) {
        renderPapersList();
    } else {
        renderAllPapers();
    }

    // processing queue
    processAnalysisQueue();
    updateTaskIndicator();
}

// Process interpretation queue（Globally unique queue to ensure that only one task is executed at the same time）
async function processAnalysisQueue() {
    // Strict check: if it is being interpreted or the queue is empty, return directly
    if (isAnalyzing) {
        return; // There is already a task being executed and no new task will be started.
    }
    if (analysisQueue.length === 0) {
        return; // Queue is empty
    }

    // Atomic setting: set the flag first, then get the task
    isAnalyzing = true;
    const paperId = analysisQueue.shift();
    saveQueuesToStorage();

    try {
        // The update status is in interpretation
        updateAnalysisStatus(paperId, 'analyzing');

        // Get settings
        const settings = await getAnalysisSettings();
        if (!settings) {
            throw new Error('Settings not configured');
        }
        const llmCfg = getAgenticLLMConfig(settings, 'interpret');
        if (!isAgenticLLMConfigured(llmCfg)) {
            throw new Error('LLM settings not configured');
        }

        // Get user AI language preference (default to English)
        const userSettings = await getUserSettings();
        const aiLanguage = (userSettings && userSettings.aiLanguage) ? userSettings.aiLanguage : 'zh';

        // Always send empty system_prompt, backend will use built-in prompt based on ai_language
        const response = await fetch('/api/paper/analyze', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                paper_id: paperId,
                openai_base_url: llmCfg.llmBaseUrl,
                openai_api_key: llmCfg.llmApiKey,
                openai_model: llmCfg.llmModel,
                system_prompt: '',
                ai_language: aiLanguage
            })
        });

        const result = await response.json();

        if (response.ok && result.success) {
            // keep task_id
            updateAnalysisStatus(paperId, 'analyzing', null, result.task_id);

            // Start polling logs
            startAnalysisLogPolling(result.task_id, paperId);

            // Polling task status
            pollAnalysisStatus(result.task_id, paperId);
        } else {
            throw new Error(result.error || 'Failed to start interpretation');
        }
    } catch (error) {
        console.error('Interpretation failed:', error);
        showMessage(`Interpretation failed: ${error.message}`, 'error');
        updateAnalysisStatus(paperId, 'error');
        saveQueuesToStorage();
        isAnalyzing = false;
        processAnalysisQueue(); // Continue processing the queue
    }
}

// Polling interpretation status
async function pollAnalysisStatus(taskId, paperId) {
    const maxAttempts = 3600; // polling at most1Hour（once per second）
    let attempts = 0;

    const poll = async () => {
        if (attempts >= maxAttempts) {
            updateAnalysisStatus(paperId, 'error');
            isAnalyzing = false;
            processAnalysisQueue();
            return;
        }

        try {
            const response = await fetch(`/api/paper/analyze/${taskId}/logs`);
            const result = await response.json();

            if (response.ok && result.success) {
                if (result.status === 'completed') {
                    updateAnalysisStatus(paperId, 'completed');
                    const paper = papers.find(p => p.id === paperId);
                    if (paper && result.result && result.result.success) {
                        paper.has_analysis_result = true;
                        paper.analysis_result_path = result.result.result_file;
                    }
                    isAnalyzing = false;
                    stopAnalysisLogPolling(taskId);
                    // When the interpretation is completed, the status column will be automatically updated.
                    // Refresh the list based on the current view mode
                    await refreshCurrentViewList();
                    if (currentPaperId === paperId) {
                        loadPaperInfo(paperId);
                    }
                    processAnalysisQueue(); // Continue processing the queue
                } else if (result.status === 'failed' || result.status === 'cancelled') {
                    updateAnalysisStatus(paperId, 'error');
                    isAnalyzing = false;
                    stopAnalysisLogPolling(taskId);
                    // No error message is shown when canceling, only shown on actual failure
                    // exit code -15 yes SIGTERM, indicating that the user actively cancels and no error is displayed.
                    const errorMsg = result.result?.error || '';
                    const isCancelled = result.status === 'cancelled' || errorMsg.includes('-15') || errorMsg.includes('-9');
                    if (result.status === 'failed' && !isCancelled) {
                        showMessage(`Interpretation failed: ${errorMsg || 'unknown error'}`, 'error');
                    }
                    processAnalysisQueue(); // Continue processing the queue
                } else {
                    // Still running, keep polling
                    attempts++;
                    setTimeout(poll, 1000);
                }
            } else {
                throw new Error(result.error || 'Failed to get status');
            }
        } catch (error) {
            console.error('Polling status failed:', error);
            attempts++;
            setTimeout(poll, 1000);
        }
    };

    poll();
}

// Update interpretation status
function updateAnalysisStatus(paperId, status, queuePosition = null, taskId = null) {
    if (!analysisStatus[paperId]) {
        analysisStatus[paperId] = {};
    }

    analysisStatus[paperId].status = status;
    if (queuePosition !== null) {
        analysisStatus[paperId].queuePosition = queuePosition;
    }
    if (taskId !== null || analysisStatus[paperId].taskId) {
        analysisStatus[paperId].taskId = taskId || analysisStatus[paperId].taskId;
    }

    // If completed or with error, remove from status（Avoid rotating status being displayed all the time）
    if (status === 'completed' || status === 'error') {
        delete analysisStatus[paperId];
    }

    // Update status display（According to the current view mode）
    if (currentViewMode === 'reading-list') {
        // If you are viewing a to-read list, only update the status of a single paper without reloading the entire list
        updatePaperStatusDisplay(paperId);
    } else if (currentCategoryId) {
        updatePaperStatusDisplay(paperId);
    } else {
        // If no category is selected, re-render the recent reading list to update the status
        renderRecentIfNoCategory();
    }
    updateTaskIndicator();
    saveQueuesToStorage();
}

// Update paper status display（Without reloading the entire list）
function updatePaperStatusDisplay(paperId) {
    const paperItem = document.querySelector(`.paper-item[data-paper-id="${paperId}"]`);
    if (!paperItem) return;

    const paper = papers.find(p => p.id === paperId);
    if (!paper) return;

    // Update status column in list view（.paper-col-action）
    const actionCols = paperItem.querySelectorAll('.paper-col-action');
    if (actionCols.length >= 2) {
        // Translation column is first .paper-col-action（index0Is the first operation column after the icon column）
        // Actually in order they are:icon, title, date, translate(0), analyze(1), reading(2)
        // but .paper-col-action Include only translate, analyze, reading
        const translateActionCol = actionCols[0];
        const analyzeActionCol = actionCols[1];

        // Update translation column
        const tStatus = translationStatus[paperId];
        let translateColHtml = '';
        if (tStatus && tStatus.status === 'translating') {
            const progress = clampProgress(tStatus.progress ?? 0);
            translateColHtml = `
            <div style="display: flex; flex-direction: column; width: 100%; gap: 4px;">
                <div style="display: flex; justify-content: space-between; align-items: center; line-height: 1;">
                    <div style="display: flex; align-items: center; gap: 4px;">
                        <button class="paper-action-log" onclick="showTranslationLogs('${paperId}', event)" title="View logs"><i class="fas fa-list"></i></button>
                        <span style="font-size: 11px; color: #007bff; font-weight: 500;">${Math.round(progress)}%</span>
                    </div>
                    <button onclick="cancelTranslationFromStatus('${paperId}', event)" title="Cancel translation" style="font-size: 10px; padding: 2px 6px; border: 1px solid #dc3545; background: #fff; color: #dc3545; border-radius: 4px; cursor: pointer; display: flex; align-items: center; gap: 3px; line-height: 1;">
                        <i class="fas fa-stop" style="font-size: 8px;"></i> Cancel
                    </button>
                </div>
                <div class="progress-bar-container translation-progress-bar" style="height: 4px; background: #e9ecef; border-radius: 2px;">
                    <div class="progress-bar" style="width: ${progress}%; background-color: #007bff; height: 100%; border-radius: 2px; transition: width 0.3s;"></div>
                </div>
            </div>`;
        } else if (tStatus && tStatus.status === 'queued') {
            const currentIndex = translationQueue.indexOf(paperId) + 1;
            const queueText = currentIndex > 0 ? `Queue ${currentIndex}` : 'Queueing';
            translateColHtml = `
            <div style="display: flex; flex-direction: column; width: 100%; gap: 4px;">
                <div style="display: flex; justify-content: space-between; align-items: center; line-height: 1;">
                    <span style="font-size: 11px; color: #ffc107; display: flex; align-items: center; gap: 4px;">
                        <i class="fas fa-clock" style="font-size: 10px;"></i> ${queueText}
                    </span>
                    <button onclick="cancelTranslationFromQueue('${paperId}', event)" title="Cancel queue" style="font-size: 10px; padding: 2px 6px; border: 1px solid #dc3545; background: #fff; color: #dc3545; border-radius: 4px; cursor: pointer; display: flex; align-items: center; gap: 3px; line-height: 1;">
                        <i class="fas fa-times" style="font-size: 8px;"></i> Cancel
                    </button>
                </div>
            </div>`;
        } else if (paper.has_chinese_version) {
            translateColHtml = `<button class="paper-col-btn view chinese" onclick="openChineseVersion('${paperId}', event)"><i class="fas fa-language"></i> Chinese version</button>`;
        } else {
            translateColHtml = `<button class="paper-col-btn translate icon-only" onclick="requestTranslation('${paperId}', event)" title="AI Translate"><i class="fas fa-language"></i></button>`;
        }
        translateActionCol.innerHTML = translateColHtml;

        // Update interpretation column
        const aStatus = analysisStatus[paperId];
        let analyzeColHtml = '';
        if (aStatus && aStatus.status === 'analyzing') {
            const progress = clampProgress(aStatus.progress ?? 0);
            // Estimate step text
            let stepText = 'Processing...';
            if (aStatus.step === 'pdf2md') stepText = 'Parsing PDF';
            else if (aStatus.step === 'llm_analysis') stepText = 'AI Thinking';

            analyzeColHtml = `
            <div style="display: flex; flex-direction: column; width: 100%; gap: 4px;">
                <div style="display: flex; justify-content: space-between; align-items: center; line-height: 1;">
                    <div style="display: flex; align-items: center; gap: 4px;">
                         <button class="paper-action-log" onclick="showAnalysisLogs('${paperId}', event)" title="View logs"><i class="fas fa-list"></i></button>
                        <span style="font-size: 11px; color: #6f42c1; font-weight: 500;">${Math.round(progress)}%</span>
                    </div>
                    <button onclick="cancelAnalysis('${paperId}', event)" title="Cancel interpretation" style="font-size: 10px; padding: 2px 6px; border: 1px solid #dc3545; background: #fff; color: #dc3545; border-radius: 4px; cursor: pointer; display: flex; align-items: center; gap: 3px; line-height: 1;">
                        <i class="fas fa-stop" style="font-size: 8px;"></i> Cancel
                    </button>
                </div>
                <div class="progress-bar-container" style="height: 4px; background: #e9ecef; border-radius: 2px; width: 100%;">
                    <div class="progress-bar" style="width: ${progress}%; background-color: #6f42c1; height: 100%; border-radius: 2px; transition: width 0.3s;"></div>
                </div>
            </div>`;
        } else if (aStatus && aStatus.status === 'queued') {
            const currentIndex = analysisQueue.indexOf(paperId) + 1;
            const queueText = currentIndex > 0 ? `Queue ${currentIndex}` : 'Queueing';
            analyzeColHtml = `
            <div style="display: flex; flex-direction: column; width: 100%; gap: 4px;">
                <div style="display: flex; justify-content: space-between; align-items: center; line-height: 1;">
                    <span style="font-size: 11px; color: #ffc107; display: flex; align-items: center; gap: 4px;">
                        <i class="fas fa-clock" style="font-size: 10px;"></i> ${queueText}
                    </span>
                    <button onclick="cancelAnalysis('${paperId}', event)" title="Cancel queue" style="font-size: 10px; padding: 2px 6px; border: 1px solid #dc3545; background: #fff; color: #dc3545; border-radius: 4px; cursor: pointer; display: flex; align-items: center; gap: 3px; line-height: 1;">
                        <i class="fas fa-times" style="font-size: 8px;"></i> Cancel
                    </button>
                </div>
            </div>`;
        } else if (paper.has_analysis_result) {
            analyzeColHtml = `<button class="paper-col-btn view analysis" onclick="viewAnalysisResult('${paperId}', event)"><i class="fas fa-brain"></i> AI Interpretation</button>`;
        } else {
            analyzeColHtml = `<button class="paper-col-btn analyze icon-only" onclick="requestAnalysis('${paperId}', event)" title="AI Interpretation"><i class="fas fa-brain"></i></button>`;
        }
        analyzeActionCol.innerHTML = analyzeColHtml;
    }

    // Update simultaneously .paper-meta in state（for detail view）
    const paperMeta = paperItem.querySelector('.paper-meta');
    if (paperMeta) {
        // Update translation status
        const translationStatusHtml = getTranslationStatusText(paperId);
        const oldTranslationStatus = paperMeta.querySelector('.translation-status');
        if (oldTranslationStatus) {
            oldTranslationStatus.remove();
        }
        if (translationStatusHtml) {
            const statusDiv = document.createElement('span');
            statusDiv.className = 'translation-status';
            statusDiv.innerHTML = translationStatusHtml;
            // Insert into meta starting position
            paperMeta.insertBefore(statusDiv, paperMeta.firstChild);
        }

        // Update interpretation status
        const analysisStatusHtml = getAnalysisStatusText(paperId);
        const oldAnalysisStatus = paperMeta.querySelector('.analysis-status');
        if (oldAnalysisStatus) {
            oldAnalysisStatus.remove();
        }
        if (analysisStatusHtml) {
            const statusDiv = document.createElement('span');
            statusDiv.className = 'analysis-status';
            statusDiv.innerHTML = analysisStatusHtml;
            paperMeta.appendChild(statusDiv);
        }

        // Update view results button
        // Check if it needs to be displayed"View Chinese version"button
        const existingChineseBtn = paperItem.querySelector('.chinese-version-btn-container .chinese-version-btn[onclick*="openChineseVersion"]');
        if (paper.has_chinese_version && !existingChineseBtn) {
            const btnContainer = paperItem.querySelector('.paper-details');
            if (btnContainer) {
                const btnHtml = `
                    <div class="chinese-version-btn-container" style="margin-top: 5px;">
                        <button class="chinese-version-btn" onclick="openChineseVersion('${paperId}', event)" title="View Chinese versionPDF">
                            <i class="fas fa-language"></i> View Chinese version
                        </button>
                    </div>
                `;
                btnContainer.insertAdjacentHTML('beforeend', btnHtml);
            }
        }

        // Check if it needs to be displayed"Check AI Interpretation"button
        const existingAnalysisBtn = paperItem.querySelector('.chinese-version-btn-container .chinese-version-btn[onclick*="viewAnalysisResult"]');
        if (paper.has_analysis_result) {
            if (!existingAnalysisBtn) {
                const btnContainer = paperItem.querySelector('.paper-details');
                if (btnContainer) {
                    const btnHtml = `
                        <div class="chinese-version-btn-container" style="margin-top: 5px;">
                            <button class="chinese-version-btn" onclick="viewAnalysisResult('${paperId}', event)" title="Check AI Interpretation" style="background: #6f42c1; color: white; border-color: #6f42c1;">
                                <i class="fas fa-brain"></i> Check AI Interpretation
                            </button>
                        </div>
                    `;
                    btnContainer.insertAdjacentHTML('beforeend', btnHtml);
                }
            }
        }
    }
}

// Get interpretation status display text
function getAnalysisStatusText(paperId) {
    const status = analysisStatus[paperId];
    if (!status) return '';

    if (status.status === 'analyzing') {
        const step = status.step === 'pdf2md' ? 'PDFchangeMarkdown' : status.step === 'llm_analysis' ? 'LLMInterpretation' : 'Interpreting';
        return `<span class="translation-status translating">
            <i class="fas fa-spinner fa-spin"></i> Interpreting (${step})...
            <button class="status-cancel-btn" onclick="cancelAnalysisFromStatus('${paperId}', event)" title="Cancel interpretation">
                <i class="fas fa-times"></i>
            </button>
        </span>`;
    } else if (status.status === 'queued') {
        const currentIndex = analysisQueue.indexOf(paperId) + 1;
        return `<span class="translation-status queued">
            <i class="fas fa-clock"></i> Interpretation queue (${currentIndex}/${analysisQueue.length})
            <button class="status-cancel-btn" onclick="cancelAnalysisFromQueue('${paperId}', event)" title="Cancel queue">
                <i class="fas fa-times"></i>
            </button>
        </span>`;
    } else if (status.status === 'completed') {
        // Don't show status text on completion because there is already"Check AI Interpretation"button
        return '';
    }
    return '';
}

// Start polling and interpreting logs
function startAnalysisLogPolling(taskId, paperId) {
    if (analysisLogInterval[taskId]) {
        clearInterval(analysisLogInterval[taskId]);
    }

    analysisLogInterval[taskId] = setInterval(async () => {
        try {
            const response = await fetch(`/api/paper/analyze/${taskId}/logs`);
            const result = await response.json();

            if (response.ok && result.success) {
                const status = result.status;

                // Detect whether the task was terminated or failed
                if (status === 'completed' || status === 'failed' || status === 'cancelled') {
                    clearInterval(analysisLogInterval[taskId]);
                    delete analysisLogInterval[taskId];

                    // update status
                    if (status === 'completed') {
                        updateAnalysisStatus(paperId, 'completed');
                        // When the interpretation is completed, the status column will be automatically updated.
                    } else {
                        updateAnalysisStatus(paperId, 'error');
                        // No error message is shown when canceling, only shown on actual failure
                        // exit code -15 yes SIGTERM, indicating that the user actively cancels and no error is displayed.
                        const errorMsg = result.result?.error || '';
                        const isCancelled = status === 'cancelled' || errorMsg.includes('-15') || errorMsg.includes('-9');
                        if (status === 'failed' && !isCancelled) {
                            showMessage(`Interpretation failed: ${errorMsg || 'unknown error'}`, 'error');
                        }
                    }

                    // Continue processing the queue
                    isAnalyzing = false;
                    updatePaperStatusDisplay(paperId);
                    processAnalysisQueue();
                } else {
                    // Update step information and progress（Don't reload the entire list to avoid flickering）
                    if (analysisStatus[paperId]) {
                        if (result.step) analysisStatus[paperId].step = result.step;
                        if (result.progress !== undefined) analysisStatus[paperId].progress = result.progress;
                        updatePaperStatusDisplay(paperId);
                    }
                }
            } else {
                // If the task does not exist（May be deleted externally or the server restarted）, stop polling and clean up the status
                if (response.status === 404) {
                    clearInterval(analysisLogInterval[taskId]);
                    delete analysisLogInterval[taskId];
                    // Remove from queue
                    const queueIndex = analysisQueue.indexOf(paperId);
                    if (queueIndex !== -1) {
                        analysisQueue.splice(queueIndex, 1);
                    }
                    // delete status
                    delete analysisStatus[paperId];
                    // reset flag
                    isAnalyzing = false;
                    saveQueuesToStorage();
                    updateTaskIndicator();
                    // Update display based on current view mode
                    if (currentViewMode === 'reading-list') {
                        updatePaperStatusDisplay(paperId);
                    } else if (currentCategoryId) {
                        updatePaperStatusDisplay(paperId);
                    } else {
                        renderRecentIfNoCategory();
                    }
                    processAnalysisQueue();
                }
            }
        } catch (error) {
            console.error('Failed to get log:', error);
        }
    }, 2000); // Every2Poll once per second
}

// Stop polling and interpreting logs
function stopAnalysisLogPolling(taskId) {
    if (analysisLogInterval[taskId]) {
        clearInterval(analysisLogInterval[taskId]);
        delete analysisLogInterval[taskId];
    }
}

// Show interpretation log
async function showAnalysisLogs(paperId, event) {
    if (event) {
        event.stopPropagation();
    }

    const status = analysisStatus[paperId];
    if (!status || !status.taskId) {
        showMessage('Interpretation task not found', 'error');
        return;
    }

    const taskId = status.taskId;

    try {
        const response = await fetch(`/api/paper/analyze/${taskId}/logs`);
        const result = await response.json();

        if (response.ok && result.success) {
            showAnalysisLogModal(taskId, result.logs, result.status, result.step, paperId);
        } else {
            showMessage(result.error || 'Failed to get log', 'error');
        }
    } catch (error) {
        console.error('Failed to get log:', error);
        showMessage('Failed to get log', 'error');
    }
}

// Show interpretation log modal box
function showAnalysisLogModal(taskId, logs, status, step, paperId) {
    const modalTitle = document.querySelector('#modal-title');
    const modalBody = document.querySelector('#modal-body');
    const confirmBtn = document.querySelector('#modal-confirm');
    const cancelBtn = document.querySelector('#modal-cancel');

    modalTitle.textContent = 'Interpret logs';
    modalBody.innerHTML = `
        <div style="margin-bottom: 10px;">
            <strong>state:</strong> <span id="log-status">${getStatusText(status)}</span>
            ${step ? `<br><strong>current step:</strong> ${step === 'pdf2md' ? 'PDFchangeMarkdown' : step === 'llm_analysis' ? 'LLMInterpretation' : step}` : ''}
        </div>
        <div style="background: #1e1e1e; color: #d4d4d4; padding: 15px; border-radius: 4px; max-height: 400px; overflow-y: auto; font-family: 'Courier New', monospace; font-size: 12px; white-space: pre-wrap; word-wrap: break-word;" id="log-content">
            ${logs.map(log => escapeHtml(log)).join('\n')}
        </div>
    `;

    confirmBtn.style.display = status === 'running' ? 'inline-block' : 'none';
    confirmBtn.textContent = 'Cancel interpretation';
    cancelBtn.textContent = 'closure';

    // Clear previous event listeners
    const confirmBtnClone = confirmBtn.cloneNode(true);
    const cancelBtnClone = cancelBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(confirmBtnClone, confirmBtn);
    cancelBtn.parentNode.replaceChild(cancelBtnClone, cancelBtn);

    const newConfirmBtn = document.getElementById('modal-confirm');
    const newCancelBtn = document.getElementById('modal-cancel');

    if (status === 'running') {
        newConfirmBtn.onclick = async (e) => {
            e.preventDefault();
            e.stopPropagation();
            await cancelAnalysisTask(taskId, paperId);
        };
    }

    newCancelBtn.onclick = (e) => {
        e.preventDefault();
        e.stopPropagation();
        hideModal();
    };

    showModal();

    // If the task is running, start automatically refreshing the log
    if (status === 'running') {
        const logInterval = setInterval(async () => {
            try {
                const response = await fetch(`/api/paper/analyze/${taskId}/logs`);
                const result = await response.json();

                if (response.ok && result.success) {
                    const logContent = document.getElementById('log-content');
                    const logStatus = document.getElementById('log-status');
                    if (logContent) {
                        logContent.textContent = result.logs.map(log => escapeHtml(log)).join('\n');
                        logContent.scrollTop = logContent.scrollHeight;
                    }
                    if (logStatus) {
                        logStatus.textContent = getStatusText(result.status);
                    }

                    // If the task is completed, stop refreshing
                    if (result.status !== 'running') {
                        clearInterval(logInterval);
                        if (result.status === 'completed') {
                            // When the interpretation is completed, the status column will be automatically updated.
                            // Update status display（Don't reload the entire list to avoid flickering）
                            updateAnalysisStatus(paperId, 'completed');
                            updatePaperStatusDisplay(paperId);
                        }
                    }
                }
            } catch (error) {
                console.error('Failed to refresh log:', error);
            }
        }, 2000);

        // When the modal is closed, clear the timer
        const originalHideModal = window.hideModal;
        window.hideModal = function () {
            clearInterval(logInterval);
            if (originalHideModal) {
                originalHideModal();
            }
        };
    }
}

// Cancel interpretation task（Cancel from status, requiredtaskId）
async function cancelAnalysisTask(taskId, paperId) {
    try {
        const response = await fetch(`/api/paper/analyze/${taskId}/cancel`, {
            method: 'POST'
        });

        const result = await response.json();

        if (response.ok && result.success) {
            // Interpretation has been cancelled, the status column will be updated automatically
            updateAnalysisStatus(paperId, 'error');
            isAnalyzing = false;
            processAnalysisQueue();
            hideModal();
        } else {
            // If the task does not exist（Server restart, etc.）, clean up the front-end status
            if (response.status === 404 || (result.error && result.error.includes('Task does not exist'))) {
                showMessage('The task does not exist and has been cleared', 'warning');
                // Check if interpreting（Check before deleting status）
                const wasAnalyzing = isAnalyzing && analysisStatus[paperId] && analysisStatus[paperId].taskId === taskId;
                // Clean up frontend state
                stopAnalysisLogPolling(taskId);
                // Remove from queue
                const queueIndex = analysisQueue.indexOf(paperId);
                if (queueIndex !== -1) {
                    analysisQueue.splice(queueIndex, 1);
                }
                // delete status
                delete analysisStatus[paperId];
                // If interpreting, reset flag
                if (wasAnalyzing) {
                    isAnalyzing = false;
                }
                saveQueuesToStorage();
                updateTaskIndicator();
                // Update display based on current view mode
                if (currentViewMode === 'reading-list') {
                    updatePaperStatusDisplay(paperId);
                } else if (currentCategoryId) {
                    updatePaperStatusDisplay(paperId);
                } else {
                    await refreshCurrentViewList();
                }
                hideModal();
                // Continue processing the queue
                processAnalysisQueue();
            } else {
                showMessage(result.error || 'Cancellation failed', 'error');
            }
        }
    } catch (error) {
        console.error('Failed to cancel interpretation:', error);
        showMessage('Cancellation failed', 'error');
    }
}

// Cancel interpretation from status（passpaperIdFindtaskId）
async function cancelAnalysisFromStatus(paperId, event) {
    if (event) event.stopPropagation();
    const status = analysisStatus[paperId];
    if (!status || !status.taskId) {
        showMessage('Interpretation task not found', 'warning');
        return;
    }
    if (!confirm('Are you sure you want to terminate the interpretation?')) {
        return;
    }
    await cancelAnalysisTask(status.taskId, paperId);
}

// Cancel interpretation from queue
async function cancelAnalysisFromQueue(paperId, event) {
    if (event) event.stopPropagation();
    const index = analysisQueue.indexOf(paperId);
    if (index === -1) {
        showMessage('The paper is not in the queue', 'warning');
        return;
    }
    analysisQueue.splice(index, 1);
    saveQueuesToStorage();
    delete analysisStatus[paperId];
    // Update the display directly without calling updateAnalysisStatus（Because the status has been deleted）
    updatePaperStatusDisplay(paperId);
    updateTaskIndicator();
    // Removed from queue, status column will update automatically
}

// View interpretation results（Displayed in the information panel on the right, widen the panel width）
async function viewAnalysisResult(paperId, event) {
    if (event) { event.stopPropagation(); }

    try {
        const response = await fetch(`/api/paper/${paperId}/analysis/result`);
        const result = await response.json();
        if (!response.ok || !result.success) {
            showMessage(result.error || 'Failed to get results', 'error');
            return;
        }

        const panel = document.querySelector('.info-panel');
        const paperInfoEl = document.getElementById('paper-info');
        if (!panel || !paperInfoEl) return;

        showInfoPanel();
        // widened panel
        panel.classList.add('wide');
        // Clean up LLM output
        let markdownContent = result.content || '';


        markdownContent = markdownContent.replace(/<think>[\s\S]*?<\/think>/gi, '');


        markdownContent = markdownContent.replace(/^```[a-zA-Z]*\n/, '');


        markdownContent = markdownContent.replace(/```$/, '');

        // 4. 去除首尾多余空格
        markdownContent = markdownContent.trim();


        const imageRegex = /!\[([^\]]*)\]\(([^)]+)\)/g;
        markdownContent = markdownContent.replace(imageRegex, (match, alt, src) => {
            if (!src.startsWith('http') && !src.startsWith('/')) {
                const encodedPath = encodeURIComponent(src);
                return `![${alt}](/api/paper/${paperId}/analysis/image?path=${encodedPath})`;
            }
            return match;
        });

        // rendering markdown（Protect formula fragments from being marked rewrite）
        if (typeof marked !== 'undefined') {
            marked.setOptions({
                breaks: true,
                gfm: true,
                highlight: function (code, lang) {
                    if (typeof hljs !== 'undefined' && lang) {
                        try { return hljs.highlight(code, { language: lang }).value; }
                        catch (e) { return hljs.highlightAuto(code).value; }
                    }
                    return code;
                }
            });
        }

        let htmlContent = '';
        if (typeof marked !== 'undefined') {
            const preserved = [];
            const mdPreserved = markdownContent
                .replace(/\$\$([\s\S]*?)\$\$/g, function (match) {
                    const id = preserved.length;
                    preserved.push(match);
                    return `@@MJX_BLOCK_${id}@@`;
                })
                .replace(/(?<!\\)\$([^\n$]+)\$/g, function (match) {
                    const id = preserved.length;
                    preserved.push(match);
                    return `@@MJX_INLINE_${id}@@`;
                });
            htmlContent = marked.parse(mdPreserved).replace(/@@MJX_(BLOCK|INLINE)_(\d+)@@/g, function (_, __, idx) {
                return preserved[Number(idx)];
            });
        } else {
            htmlContent = `<pre style="white-space: pre-wrap;">${escapeHtml(markdownContent)}</pre>`;
        }

        // Inject toolbar + content
        paperInfoEl.innerHTML = `
            <div class="paper-info-toolbar">
                <div style="font-weight:600;">AI Interpretation</div>
            </div>
            <button class="analysis-fullscreen-btn" onclick="openAnalysisFullscreen('${paperId}')" title="View full screen"><i class="fas fa-expand"></i></button>
            <button class="analysis-close-btn" onclick="closeAnalysisView()" title="closure"><i class="fas fa-times"></i></button>
            <div class="paper-info-content markdown-viewer">${htmlContent}</div>
        `;

        // code highlighting
        if (typeof hljs !== 'undefined') {
            paperInfoEl.querySelectorAll('pre code').forEach((block) => hljs.highlightElement(block));
        }

        // Apply styles（if necessary）
        if (typeof applyMarkdownStyles === 'function') {
            applyMarkdownStyles();
        }

        // Mathematical formula typesetting（MathJax）
        const el = paperInfoEl.querySelector('.paper-info-content');
        if (window.MathJax && MathJax.startup && MathJax.startup.promise) {
            MathJax.startup.promise.then(() => {
                if (MathJax.typesetPromise) {
                    MathJax.typesetPromise([el]);
                } else if (MathJax.typeset) {
                    MathJax.typeset([el]);
                }
            });
        } else if (window.MathJax) {
            if (MathJax.typesetPromise) {
                MathJax.typesetPromise([el]);
            } else if (MathJax.typeset) {
                MathJax.typeset([el]);
            }
        } else {
            setTimeout(() => {
                if (window.MathJax && MathJax.typesetPromise) {
                    MathJax.typesetPromise([el]);
                }
            }, 500);
        }
    } catch (e) {
        console.error('Failed to get results:', e);
        showMessage('Failed to get results', 'error');
    }
}


// View full screen AI Interpretation
function openAnalysisFullscreen(paperId) {
    // Open full screen viewer in new window
    const url = `/viewer/analysis/${paperId}`;
    window.open(url, '_blank', 'width=1200,height=800');
}

function closeAnalysisView() {
    const panel = document.querySelector('.info-panel');
    if (panel) {
        panel.classList.remove('wide');
        // Clear inline styles and restore default width（passCSSclass control）
        panel.style.width = '';
    }
    // Restore current paper information
    if (currentPaperId) {
        loadPaperInfo(currentPaperId);
    } else {
        document.getElementById('paper-info').innerHTML = '';
        if (currentViewMode === 'reading-list') {
            hideInfoPanel();
        }
    }
}

// application Markdown style
function applyMarkdownStyles() {
    const style = document.createElement('style');
    style.id = 'markdown-viewer-styles';
    if (document.getElementById('markdown-viewer-styles')) {
        return; // Style already exists
    }
    style.textContent = `
        .markdown-viewer h1, .markdown-viewer h2, .markdown-viewer h3, 
        .markdown-viewer h4, .markdown-viewer h5, .markdown-viewer h6 {
            margin-top: 24px;
            margin-bottom: 16px;
            font-weight: 600;
            line-height: 1.25;
        }
        .markdown-viewer h1 { font-size: 2em; border-bottom: 1px solid #eaecef; padding-bottom: 0.3em; }
        .markdown-viewer h2 { font-size: 1.5em; border-bottom: 1px solid #eaecef; padding-bottom: 0.3em; }
        .markdown-viewer h3 { font-size: 1.25em; }
        .markdown-viewer h4 { font-size: 1em; }
        .markdown-viewer p { margin-bottom: 16px; line-height: 1.6; }
        .markdown-viewer ul, .markdown-viewer ol { margin-bottom: 16px; padding-left: 2em; }
        .markdown-viewer li { margin-bottom: 0.25em; }
        .markdown-viewer blockquote {
            padding: 0 1em;
            color: #6a737d;
            border-left: 0.25em solid #dfe2e5;
            margin-bottom: 16px;
        }
        .markdown-viewer code {
            padding: 0.2em 0.4em;
            margin: 0;
            font-size: 85%;
            background-color: rgba(27,31,35,0.05);
            border-radius: 3px;
            font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
        }
        .markdown-viewer pre {
            padding: 16px;
            overflow: auto;
            font-size: 85%;
            line-height: 1.45;
            background-color: #f6f8fa;
            border-radius: 6px;
            margin-bottom: 16px;
        }
        .markdown-viewer pre code {
            display: inline;
            padding: 0;
            margin: 0;
            overflow: visible;
            line-height: inherit;
            word-wrap: normal;
            background-color: transparent;
            border: 0;
        }
        .markdown-viewer img {
            max-width: 100%;
            height: auto;
            margin: 16px 0;
            border-radius: 4px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .markdown-viewer table {
            border-collapse: collapse;
            margin-bottom: 16px;
            width: 100%;
        }
        .markdown-viewer table th,
        .markdown-viewer table td {
            padding: 6px 13px;
            border: 1px solid #dfe2e5;
        }
        .markdown-viewer table th {
            background-color: #f6f8fa;
            font-weight: 600;
        }
        .markdown-viewer hr {
            height: 0.25em;
            padding: 0;
            margin: 24px 0;
            background-color: #e1e4e8;
            border: 0;
        }
        .markdown-viewer a {
            color: #0366d6;
            text-decoration: none;
        }
        .markdown-viewer a:hover {
            text-decoration: underline;
        }
    `;
    document.head.appendChild(style);
}

// Left category column width adjustment function
function setupSidebarResizing() {
    const resizer = document.getElementById('sidebar-resizer');
    const sidebar = document.querySelector('.sidebar');

    if (!resizer || !sidebar) return;

    resizer.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();

        const startX = e.pageX;
        const startWidth = sidebar.offsetWidth;

        resizer.classList.add('resizing');

        const onMouseMove = (e) => {
            e.preventDefault();
            // Dragging to the right is a positive number, dragging to the left is a negative number
            const diff = e.pageX - startX;
            const newWidth = Math.max(200, Math.min(window.innerWidth * 0.5, startWidth + diff));

            requestAnimationFrame(() => {
                sidebar.style.width = newWidth + 'px';
            });
        };

        const onMouseUp = () => {
            resizer.classList.remove('resizing');
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
        };

        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
    });
}

// Right panel width adjustment function
function setupInfoPanelResizing() {
    const resizer = document.getElementById('info-panel-resizer');
    const panel = document.getElementById('info-panel');

    if (!resizer || !panel) return;

    resizer.addEventListener('mousedown', (e) => {
        e.preventDefault();
        e.stopPropagation();

        const startX = e.pageX;
        const startWidth = panel.offsetWidth;

        resizer.classList.add('resizing');

        const onMouseMove = (e) => {
            e.preventDefault();
            // Dragging to the left is a positive number, dragging to the right is a negative number
            const diff = startX - e.pageX;
            const newWidth = Math.max(280, Math.min(window.innerWidth * 0.7, startWidth + diff));

            requestAnimationFrame(() => {
                panel.style.width = newWidth + 'px';
            });
        };

        const onMouseUp = () => {
            resizer.classList.remove('resizing');
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
        };

        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
    });
}

// Column width adjustment function
function setupColumnResizing() {
    const resizers = document.querySelectorAll('.paper-header-resizer');
    const header = document.querySelector('.paper-header');

    resizers.forEach(resizer => {
        resizer.addEventListener('mousedown', (e) => {
            e.preventDefault();
            e.stopPropagation();

            const startX = e.pageX;
            const colIndex = parseInt(resizer.dataset.col);

            // Get the current grid template
            const style = window.getComputedStyle(header);
            const cols = style.gridTemplateColumns.split(' ');
            const startWidth = parseFloat(cols[colIndex]);

            resizer.classList.add('resizing');

            // Cache all elements that need to be updated
            const items = Array.from(document.querySelectorAll('.paper-item'));

            const onMouseMove = (e) => {
                e.preventDefault();
                const diff = e.pageX - startX;
                const newWidth = Math.max(60, startWidth + diff);

                // Update directly without using intermediate variables
                cols[colIndex] = newWidth + 'px';
                const newTemplate = cols.join(' ');

                // use requestAnimationFrame Optimize performance
                requestAnimationFrame(() => {
                    header.style.gridTemplateColumns = newTemplate;
                    // Batch update all rows
                    items.forEach(item => {
                        item.style.gridTemplateColumns = newTemplate;
                    });
                });
            };

            const onMouseUp = () => {
                resizer.classList.remove('resizing');
                document.removeEventListener('mousemove', onMouseMove);
                document.removeEventListener('mouseup', onMouseUp);
            };

            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
        });
    });
}

// Cancel translation
function cancelTranslation(paperId, event) {
    if (event) event.stopPropagation();

    const status = translationStatus[paperId];
    if (!status) return;

    // Remove from queue
    const queueIndex = translationQueue.indexOf(paperId);
    if (queueIndex > -1) {
        translationQueue.splice(queueIndex, 1);
    }

    // If translation is in progress, stop the task
    if (status.taskId && status.status === 'translating') {
        fetch(`/api/paper/translate/${status.taskId}/cancel`, { method: 'POST' })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    // Translation has been canceled and the status column will be updated automatically.
                    // If this task is currently being translated, reset the translation flag
                    if (isTranslating) {
                        isTranslating = false;
                        // Continue processing the next task in the queue
                        processTranslationQueue();
                    }
                } else {
                    showMessage(data.error || 'Cancel translation failed', 'error');
                }
            })
            .catch(err => {
                console.error('Cancel translation failed:', err);
                showMessage('Cancel translation failed', 'error');
            });
    }

    // Clean status
    delete translationStatus[paperId];
    saveQueuesToStorage();
    updateTaskIndicator();

    // refresh display（According to the current view mode）
    if (currentViewMode === 'reading-list') {
        updatePaperStatusDisplay(paperId);
    } else if (currentCategoryId) {
        updatePaperStatusDisplay(paperId);
    } else {
        renderAllPapers();
    }
}

// Cancel interpretation
function cancelAnalysis(paperId, event) {
    if (event) event.stopPropagation();

    const status = analysisStatus[paperId];
    if (!status) return;

    // Remove from queue
    const queueIndex = analysisQueue.indexOf(paperId);
    if (queueIndex > -1) {
        analysisQueue.splice(queueIndex, 1);
    }

    // If interpreting, stop the task
    if (status.taskId && status.status === 'analyzing') {
        fetch(`/api/paper/analyze/${status.taskId}/cancel`, { method: 'POST' })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    // Interpretation has been cancelled, the status column will be updated automatically
                    // If this task is currently being interpreted, reset the interpretation flag
                    if (isAnalyzing) {
                        isAnalyzing = false;
                        // Continue processing the next task in the queue
                        processAnalysisQueue();
                    }
                } else {
                    showMessage(data.error || 'Failed to cancel interpretation', 'error');
                }
            })
            .catch(err => {
                console.error('Failed to cancel interpretation:', err);
                showMessage('Failed to cancel interpretation', 'error');
            });
    }

    // Clean status
    delete analysisStatus[paperId];
    saveQueuesToStorage();
    updateTaskIndicator();

    // refresh display（According to the current view mode）
    if (currentViewMode === 'reading-list') {
        updatePaperStatusDisplay(paperId);
    } else if (currentCategoryId) {
        updatePaperStatusDisplay(paperId);
    } else {
        renderAllPapers();
    }
}

// ========================================
// Daily arXiv Function
// ========================================

let dailyArxivPapers = {};  // Store by date and partition: {date: {category: [papers]}}
let dailyArxivCategories = [];
let dailyArxivCurrentCategory = 'all';  // The currently selected partition,'all' Indicates showing all partitions
let dailyArxivCurrentDate = null;  // Currently selected date
let dailyArxivAvailableDates = [];  // Available date list
let dailyArxivSettings = {
    categories: [],
    retentionDays: 7,
    checkIntervalMinutes: 10,
};
let dailyArxivEmptyDefaultHtml = null;
let dailyArxivProgressIntervals = {};  // Progress polling timer for each partition: {category: intervalId}
let dailyArxivSearchQuery = '';        // Daily arXiv Page search query
let dailyArxivLLMConfigured = false;  // LLM configuration status
let dailyArxivSlowDownloadNotified = {};  // Log whether each partition has shown a slow download prompt: {category: true}
let dailyArxivLastPaperKey = '';  // Keep track of the previous paperkey, used to detect paper switching
let dailyArxivSelectedAffiliations = new Set(); // Currently selected unit filter
let dailyArxivSelectedCountries = new Set(); // Currently selected region filter
let dailyArxivSelectedKeywords = new Set(); // Currently selected keyword filter conditions
let dailyArxivExcludedAffiliations = new Set(); // Excluded units（Reverse filtering）
let dailyArxivExcludedCountries = new Set(); // Excluded areas（Reverse filtering）
let dailyArxivExcludedKeywords = new Set(); // Excluded keywords（Reverse filtering）
let dailyArxivKnownInstitutions = new Set(); // All known institutions（System default + User defined）
let dailyArxivFilterFirstAffiliation = false; // Whether to filter the first unit
let dailyArxivFilterKnownInstitutions = false; // Whether to show only common institutions
let dailyArxivHideUnknownFirstAffiliation = false; // Whether to hide the first unit belongs to"Other institutions"thesis
let dailyArxivReadStatus = {};
let dailyArxivReadPaperIds = new Set();
let dailyArxivRerenderAfterDetailClose = false;

function loadDailyArxivReadStatus() {
    try {
        const raw = localStorage.getItem('dailyArxivReadStatus');
        const parsed = raw ? JSON.parse(raw) : {};
        if (parsed && typeof parsed === 'object') {
            dailyArxivReadStatus = parsed;
        } else {
            dailyArxivReadStatus = {};
        }
    } catch (e) {
        dailyArxivReadStatus = {};
    }
    dailyArxivReadPaperIds = new Set(Object.keys(dailyArxivReadStatus || {}));
}

function saveDailyArxivReadStatus() {
    try {
        localStorage.setItem('dailyArxivReadStatus', JSON.stringify(dailyArxivReadStatus || {}));
    } catch (e) {
    }
}

async function syncDailyArxivReadStatusFromServer(arxivIds) {
    try {
        if (!Array.isArray(arxivIds) || arxivIds.length === 0) return;
        const uniqueIds = [...new Set(arxivIds.filter(x => typeof x === 'string' && x.trim()).map(x => x.trim()))];
        if (uniqueIds.length === 0) return;

        const res = await fetch('/api/daily-arxiv/read-status', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ arxiv_ids: uniqueIds })
        });
        if (!res.ok) return;
        const data = await res.json();
        if (!data || !data.success) return;

        const readIds = Array.isArray(data.read_ids) ? data.read_ids : [];
        if (readIds.length === 0) return;

        let changed = false;
        readIds.forEach(id => {
            if (!id) return;
            if (!dailyArxivReadStatus[id]) {
                dailyArxivReadStatus[id] = Date.now();
                changed = true;
            }
        });
        if (changed) {
            dailyArxivReadPaperIds = new Set(Object.keys(dailyArxivReadStatus || {}));
            saveDailyArxivReadStatus();
        }
    } catch (e) {
    }
}

function markDailyArxivPaperReadOnServer(arxivId) {
    try {
        if (!arxivId) return;
        fetch('/api/daily-arxiv/read/mark', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ arxiv_id: arxivId })
        }).catch(() => { });
    } catch (e) {
    }
}

function isDailyArxivPaperRead(arxivId) {
    return !!arxivId && dailyArxivReadPaperIds.has(arxivId);
}

function markDailyArxivPaperRead(arxivId) {
    if (!arxivId) return false;
    const wasRead = isDailyArxivPaperRead(arxivId);
    dailyArxivReadStatus[arxivId] = Date.now();
    dailyArxivReadPaperIds.add(arxivId);
    saveDailyArxivReadStatus();
    markDailyArxivPaperReadOnServer(arxivId);
    return !wasRead;
}

function isDailyArxivEnabled() {
    return dailyArxivSettings && dailyArxivSettings.enabled === true;
}

function setDailyArxivEmptyState(mode) {
    const emptyEl = document.getElementById('daily-arxiv-empty');
    if (!emptyEl) return;

    if (dailyArxivEmptyDefaultHtml === null) {
        dailyArxivEmptyDefaultHtml = emptyEl.innerHTML;
    }

    const mainEl = document.querySelector('.daily-arxiv-main');
    const loadingEl = document.getElementById('daily-arxiv-loading');
    const progressEl = document.getElementById('daily-arxiv-progress');
    const filterPanel = document.getElementById('daily-arxiv-filter-panel');

    if (mode === 'disabled') {
        emptyEl.innerHTML = `
            <i class="fas fa-ban fa-3x"></i>
            <h3>Daily arXiv is disabled</h3>
            <p>Please enable it in Settings → Daily arXiv → "Enable Daily arXiv".</p>
            <button class="btn btn-primary" onclick="showDailyArxivSettingsModal()">
                <i class="fas fa-cog"></i> Open settings
            </button>
        `;
        emptyEl.style.display = 'flex';
        if (mainEl) mainEl.style.display = 'none';
        if (loadingEl) loadingEl.style.display = 'none';
        if (progressEl) progressEl.style.display = 'none';
        if (filterPanel) filterPanel.style.display = 'none';
        return;
    }

    emptyEl.innerHTML = dailyArxivEmptyDefaultHtml;
    if (mainEl) mainEl.style.display = '';
}

// Region name standardized mapping table
function normalizeCountryName(countryName) {
    if (!countryName) return '';

    const normalized = countryName.trim();

    // Standardized mapping table: mapping various variants to standard names
    const normalizationMap = {
        // Variations of the United States -> United States
        'USA': 'United States',
        'US': 'United States',
        'U.S.': 'United States',
        'U.S.A.': 'United States',
        'United States of America': 'United States',

        // Variations of the UK -> United Kingdom
        'UK': 'United Kingdom',
        'U.K.': 'United Kingdom',
        'Great Britain': 'United Kingdom',
        'Britain': 'United Kingdom',

        // Variations of China -> China
        'PRC': 'China',
        'P.R.C.': 'China',
        "People's Republic of China": 'China',

        // Variations of Korea -> South Korea
        'Korea': 'South Korea',
        'Republic of Korea': 'South Korea',
        'ROK': 'South Korea',

        // Variations of Hong Kong -> Hong Kong
        'Hong Kong SAR': 'Hong Kong',
        'Hong Kong SAR China': 'Hong Kong',
        'Hong Kong, SAR China': 'Hong Kong',
        'Hong Kong SAR, China': 'Hong Kong',
        'Hong Kong, China': 'Hong Kong',
        'HK': 'Hong Kong',

        // Variations of Macau -> Macao
        'Macau': 'Macao',
        'Macao SAR': 'Macao',
        'Macao SAR China': 'Macao',
        'Macao, SAR China': 'Macao',
        'Macao SAR, China': 'Macao',
        'Macao, China': 'Macao',
        'Macau SAR': 'Macao',
        'Macau SAR China': 'Macao',
        'Macau, SAR China': 'Macao',
        'Macau SAR, China': 'Macao',
        'Macau, China': 'Macao',

        // Variations of UAE -> United Arab Emirates
        'UAE': 'United Arab Emirates',
        'U.A.E.': 'United Arab Emirates',
    };

    // Try an exact match first
    if (normalizationMap[normalized]) {
        return normalizationMap[normalized];
    }

    // Case-insensitive matching
    const normalizedLower = normalized.toLowerCase();
    for (const [variant, standard] of Object.entries(normalizationMap)) {
        if (variant.toLowerCase() === normalizedLower) {
            return standard;
        }
    }

    // If no mapping is found, return the original name
    return normalized;
}

// Region name to flag emoji mapping
function getCountryFlag(countryName) {
    if (!countryName) return '';

    // Expanded country map with more countries and variants
    const countryMap = {
        // major countries
        'United States': '🇺🇸', 'USA': '🇺🇸', 'US': '🇺🇸', 'U.S.': '🇺🇸', 'U.S.A.': '🇺🇸', 'United States of America': '🇺🇸',
        'China': '🇨🇳', 'PRC': '🇨🇳', 'P.R.C.': '🇨🇳', "People's Republic of China": '🇨🇳',
        'United Kingdom': '🇬🇧', 'UK': '🇬🇧', 'U.K.': '🇬🇧', 'Great Britain': '🇬🇧', 'Britain': '🇬🇧',
        'Germany': '🇩🇪',
        'France': '🇫🇷',
        'Japan': '🇯🇵',
        'Canada': '🇨🇦',
        'Australia': '🇦🇺',
        'Italy': '🇮🇹',
        'Spain': '🇪🇸',
        'Netherlands': '🇳🇱',
        'Switzerland': '🇨🇭',
        'Sweden': '🇸🇪',
        'Singapore': '🇸🇬',
        'South Korea': '🇰🇷', 'Korea': '🇰🇷', 'Republic of Korea': '🇰🇷', 'ROK': '🇰🇷',
        'India': '🇮🇳',
        'Israel': '🇮🇱',
        'Belgium': '🇧🇪',
        'Austria': '🇦🇹',
        'Denmark': '🇩🇰',
        'Finland': '🇫🇮',
        'Norway': '🇳🇴',
        'Poland': '🇵🇱',
        'Russia': '🇷🇺', 'Russian Federation': '🇷🇺',
        'Brazil': '🇧🇷',
        'Mexico': '🇲🇽',
        'Taiwan': '🇹🇼',
        'Hong Kong': '🇭🇰', 'Hong Kong SAR': '🇭🇰', 'Hong Kong SAR China': '🇭🇰', 'Hong Kong, SAR China': '🇭🇰', 'Hong Kong SAR, China': '🇭🇰', 'Hong Kong, China': '🇭🇰', 'HK': '🇭🇰',
        'Macao': '🇲🇴', 'Macao SAR': '🇲🇴', 'Macao SAR China': '🇲🇴', 'Macao, SAR China': '🇲🇴', 'Macao SAR, China': '🇲🇴', 'Macao, China': '🇲🇴',
        'Macau': '🇲🇴', 'Macau SAR': '🇲🇴', 'Macau SAR China': '🇲🇴', 'Macau, SAR China': '🇲🇴', 'Macau SAR, China': '🇲🇴', 'Macau, China': '🇲🇴',
        'New Zealand': '🇳🇿',
        'Ireland': '🇮🇪',
        'Portugal': '🇵🇹',
        'Greece': '🇬🇷',
        'Czech Republic': '🇨🇿', 'Czechia': '🇨🇿',
        'Hungary': '🇭🇺',
        'Romania': '🇷🇴',
        'Turkey': '🇹🇷', 'Türkiye': '🇹🇷',
        'Saudi Arabia': '🇸🇦',
        'United Arab Emirates': '🇦🇪', 'UAE': '🇦🇪',
        'Thailand': '🇹🇭',
        'Malaysia': '🇲🇾',
        'Indonesia': '🇮🇩',
        'Philippines': '🇵🇭',
        'Vietnam': '🇻🇳', 'Viet Nam': '🇻🇳',
        'Chile': '🇨🇱',
        'Argentina': '🇦🇷',
        'South Africa': '🇿🇦',
        'Egypt': '🇪🇬',
        // Add more countries
        'Luxembourg': '🇱🇺',
        'Iceland': '🇮🇸',
        'Estonia': '🇪🇪',
        'Latvia': '🇱🇻',
        'Lithuania': '🇱🇹',
        'Slovenia': '🇸🇮',
        'Slovakia': '🇸🇰',
        'Croatia': '🇭🇷',
        'Serbia': '🇷🇸',
        'Bulgaria': '🇧🇬',
        'Ukraine': '🇺🇦',
        'Belarus': '🇧🇾',
        'Moldova': '🇲🇩',
        'Georgia': '🇬🇪',
        'Armenia': '🇦🇲',
        'Azerbaijan': '🇦🇿',
        'Kazakhstan': '🇰🇿',
        'Uzbekistan': '🇺🇿',
        'Bangladesh': '🇧🇩',
        'Pakistan': '🇵🇰',
        'Sri Lanka': '🇱🇰',
        'Nepal': '🇳🇵',
        'Myanmar': '🇲🇲', 'Burma': '🇲🇲',
        'Cambodia': '🇰🇭',
        'Laos': '🇱🇦',
        'Mongolia': '🇲🇳',
        'North Korea': '🇰🇵', 'DPRK': '🇰🇵', "Democratic People's Republic of Korea": '🇰🇵',
        'Iran': '🇮🇷',
        'Iraq': '🇮🇶',
        'Jordan': '🇯🇴',
        'Lebanon': '🇱🇧',
        'Qatar': '🇶🇦',
        'Kuwait': '🇰🇼',
        'Oman': '🇴🇲',
        'Bahrain': '🇧🇭',
        'Yemen': '🇾🇪',
        'Cyprus': '🇨🇾',
        'Malta': '🇲🇹',
        'Colombia': '🇨🇴',
        'Peru': '🇵🇪',
        'Venezuela': '🇻🇪',
        'Ecuador': '🇪🇨',
        'Bolivia': '🇧🇴',
        'Paraguay': '🇵🇾',
        'Uruguay': '🇺🇾',
        'Costa Rica': '🇨🇷',
        'Panama': '🇵🇦',
        'Guatemala': '🇬🇹',
        'Honduras': '🇭🇳',
        'El Salvador': '🇸🇻',
        'Nicaragua': '🇳🇮',
        'Cuba': '🇨🇺',
        'Jamaica': '🇯🇲',
        'Trinidad and Tobago': '🇹🇹',
        'Dominican Republic': '🇩🇴',
        'Puerto Rico': '🇵🇷',
        'Morocco': '🇲🇦',
        'Algeria': '🇩🇿',
        'Tunisia': '🇹🇳',
        'Libya': '🇱🇾',
        'Sudan': '🇸🇩',
        'Ethiopia': '🇪🇹',
        'Kenya': '🇰🇪',
        'Tanzania': '🇹🇿',
        'Uganda': '🇺🇬',
        'Ghana': '🇬🇭',
        'Nigeria': '🇳🇬',
        'Senegal': '🇸🇳',
        'Ivory Coast': '🇨🇮', "Côte d'Ivoire": '🇨🇮',
        'Cameroon': '🇨🇲',
        'Angola': '🇦🇴',
        'Mozambique': '🇲🇿',
        'Madagascar': '🇲🇬',
        'Mauritius': '🇲🇺',
        'Botswana': '🇧🇼',
        'Namibia': '🇳🇦',
        'Zimbabwe': '🇿🇼',
        'Zambia': '🇿🇲',
        'Malawi': '🇲🇼',
        'Rwanda': '🇷🇼',
        'Burundi': '🇧🇮',
        'New Caledonia': '🇳🇨',
        'Fiji': '🇫🇯',
        'Papua New Guinea': '🇵🇬',
    };

    // exact match
    if (countryMap[countryName]) {
        return countryMap[countryName];
    }

    // fuzzy matching（Not case sensitive）
    const countryLower = countryName.toLowerCase().trim();
    for (const [key, flag] of Object.entries(countryMap)) {
        if (key.toLowerCase() === countryLower) {
            return flag;
        }
    }

    // partial match（for processing "Hong Kong SAR China" Such a situation）
    // Check if a known region name is included
    for (const [key, flag] of Object.entries(countryMap)) {
        const keyLower = key.toLowerCase();
        // If the input contains keywords and the keyword length is greater than3（Avoid mismatches）
        if (keyLower.length > 3 && countryLower.includes(keyLower)) {
            return flag;
        }
    }

    // Reverse match: if the key in the mapping table contains the entered country name（Used to handle abbreviations, etc.）
    for (const [key, flag] of Object.entries(countryMap)) {
        const keyLower = key.toLowerCase();
        if (keyLower.length > 3 && keyLower.includes(countryLower)) {
            return flag;
        }
    }

    // If not found, returns an empty string
    return '';
}

// Generate string hash value（for color generation）
function stringHash(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
        const char = str.charCodeAt(i);
        hash = ((hash << 5) - hash) + char;
        hash = hash & hash;
    }
    return Math.abs(hash);
}

// Generate color based on string
function getColorForString(str) {
    const hash = stringHash(str);
    // use HSL Color space, fixed saturation and brightness, only changing hue
    const hue = hash % 360;
    return `hsl(${hue}, 70%, 45%)`;
}

// Generate background color based on string（light version）
function getBgColorForString(str) {
    const hash = stringHash(str);
    const hue = hash % 360;
    return `hsl(${hue}, 70%, 92%)`;
}

// Remove notification（With animation effect）
function removeNotificationWithAnimation(notificationId = 'daily-arxiv-api-notification') {
    const notification = document.getElementById(notificationId);
    if (notification) {
        notification.style.animation = 'slideOutRight 0.3s ease-out';
        setTimeout(() => {
            if (notification.parentElement) {
                notification.remove();
            }
        }, 300);
    }
}

// Restart Daily arXiv crawl（Test first LLM API, and then start crawling）
async function restartDailyArxivFetch() {
    // Remove existing notifications first（if there is）, give user feedback
    removeNotificationWithAnimation('daily-arxiv-api-notification');

    // Wait for the animation to complete before testing
    await new Promise(resolve => setTimeout(resolve, 350));

    // Test first LLM API
    const testResult = await testLLMAPIForDailyArxiv();
    if (!testResult.success) {
        // The test fails and the error message is redisplayed.（With refresh effect）
        const actionButton = `
            <button class="notification-action-btn" onclick="restartDailyArxivFetch()" style="
                background: #c62828;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 12px;
                font-size: 12px;
                cursor: pointer;
                margin-left: 8px;
                transition: background 0.2s;
            " onmouseover="this.style.background='#a02020'" onmouseout="this.style.background='#c62828'" title="Retest and start crawling">
                <i class="fas fa-redo"></i> Restart
            </button>
        `;
        showRoundedNotification('LLM API Call failed, stop Daily arXiv,Check, please LLM API set up.', 'error', true, 'daily-arxiv-api-notification', actionButton);
        return;
    }

    // Test passed, update configuration status
    dailyArxivLLMConfigured = true;

    // Use the currently viewed date（If not, use today's date）
    const dateToFetch = dailyArxivCurrentDate || new Date().toISOString().split('T')[0];

    // Start crawling（Decide whether to crawl a single partition or all partitions based on the current view）
    if (dailyArxivCurrentCategory && dailyArxivCurrentCategory !== 'all') {
        // Grab the current partition
        await triggerFetchPapers(false);
    } else {
        // Fetch all partitions（Use the currently viewed date）
        await triggerFetchAllCategories(false, dateToFetch);
    }
}

// examine Daily arXiv LLM Configuration
async function checkDailyArxivLLMConfig() {
    try {
        const res = await fetch('/api/daily-arxiv/check-llm-config');
        if (res.ok) {
            const data = await res.json();
            if (data.success) {
                dailyArxivLLMConfigured = data.is_configured;

                // examine LLM API whether failed
                if (data.llm_api_failed) {
                    // Display a permanent pop-up window with a restart button
                    const actionButton = `
                        <button class="notification-action-btn" onclick="restartDailyArxivFetch()" style="
                            background: #c62828;
                            color: white;
                            border: none;
                            border-radius: 4px;
                            padding: 4px 12px;
                            font-size: 12px;
                            cursor: pointer;
                            margin-left: 8px;
                            transition: background 0.2s;
                        " onmouseover="this.style.background='#a02020'" onmouseout="this.style.background='#c62828'" title="Retest and start crawling">
                            <i class="fas fa-redo"></i> Restart
                        </button>
                    `;
                    showRoundedNotification('LLM API Call failed, stop Daily arXiv,Check, please LLM API set up.', 'error', true, 'daily-arxiv-api-notification', actionButton);
                } else {
                    // if API Normal, remove the pop-up window（If present, animate）
                    removeNotificationWithAnimation('daily-arxiv-api-notification');
                }
            }
        }
    } catch (err) {
        console.error('examine LLM Configuration failed:', err);
        dailyArxivLLMConfigured = false;
    }
}

// initialization Daily arXiv
async function initDailyArxiv() {
    loadDailyArxivReadStatus();
    // examine LLM Configuration
    await checkDailyArxivLLMConfig();

    // Load settings
    await loadDailyArxivSettings();

    // Load available dates
    await loadAvailableDates();

    // Binding events
    const settingsBtn = document.getElementById('daily-arxiv-settings');
    if (settingsBtn) {
        settingsBtn.addEventListener('click', showDailyArxivSettingsModal);
    }

    // date navigation buttons
    const prevDateBtn = document.getElementById('daily-arxiv-prev-date');
    const nextDateBtn = document.getElementById('daily-arxiv-next-date');
    if (prevDateBtn) {
        prevDateBtn.addEventListener('click', () => navigateDate(-1));
    }
    if (nextDateBtn) {
        nextDateBtn.addEventListener('click', () => navigateDate(1));
    }

    const emptyEl = document.getElementById('daily-arxiv-empty');
    const gridEl = document.getElementById('daily-arxiv-grid');
    const filterBtn = document.getElementById('daily-arxiv-filter');
    const filterPanel = document.getElementById('daily-arxiv-filter-panel');
    const filterClearBtn = document.getElementById('daily-arxiv-filter-clear');
    const searchInput = document.getElementById('daily-arxiv-search');

    // Daily arXiv search:title / authors / affiliations / abstract
    if (searchInput) {
        let searchTimer = null;
        searchInput.addEventListener('input', () => {
            const query = searchInput.value || '';
            clearTimeout(searchTimer);
            searchTimer = setTimeout(() => {
                dailyArxivSearchQuery = query.trim();
                renderDailyArxivGrid();
            }, 250);
        });

        // ESC Clear search
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                searchInput.value = '';
                dailyArxivSearchQuery = '';
                renderDailyArxivGrid();
            }
        });
    }

    // Filter button: Expand/Collapse filter panel
    if (filterBtn && filterPanel) {
        filterBtn.addEventListener('click', () => {
            // Before each opening, based on the current partition & Date re-renders the unit list, region list and keyword list
            if (filterPanel.style.display === 'none' || !filterPanel.style.display) {
                renderDailyArxivFilterAffiliations();
                renderDailyArxivFilterCountries();
                renderDailyArxivFilterKeywords();
                // Initialized when first displayedresizer
                setTimeout(() => setupDailyArxivFilterResizing(), 50);
            }
            const isVisible = filterPanel.style.display !== 'none';
            filterPanel.style.display = isVisible ? 'none' : 'block';
        });
    }

    // Clear filters
    if (filterClearBtn) {
        filterClearBtn.addEventListener('click', () => {
            dailyArxivSelectedAffiliations.clear();
            dailyArxivSelectedCountries.clear();
            dailyArxivSelectedKeywords.clear();
            dailyArxivExcludedAffiliations.clear();
            dailyArxivExcludedCountries.clear();
            dailyArxivExcludedKeywords.clear();
            renderDailyArxivFilterAffiliations();
            renderDailyArxivFilterCountries();
            renderDailyArxivFilterKeywords();
            renderDailyArxivGrid();
        });
    }

    // If there is a configuration partition, initialize the display and try to load the paper
    if (dailyArxivCategories.length > 0) {
        // Hide empty status prompts for unconfigured partitions
        if (emptyEl) emptyEl.style.display = 'none';

        // Show all partitions by default
        dailyArxivCurrentCategory = 'all';
        renderDailyArxivCategoryTags();

        // Load paper
        await loadPapersForCurrentDate();

        // Check if there are partitions being fetched, if so start polling
        checkAndStartProgressPolling();
    } else {
        // No partition is configured, showing empty status
        if (emptyEl) emptyEl.style.display = 'flex';
        if (gridEl) gridEl.innerHTML = '';
    }

    // Set the drag-to-width function of the filter panel
    setupDailyArxivFilterResizing();

    // Initialize filter partition folding state（Expand by default）
    const filterSections = document.querySelectorAll('.filter-section-box');
    filterSections.forEach(section => {
        // Expand by default, do not addcollapsedkind
    });
}

// Toggle filter section collapse/Expand
function toggleFilterSection(header) {
    const sectionBox = header.closest('.filter-section-box');
    if (sectionBox) {
        sectionBox.classList.toggle('collapsed');
    }
}

// set up Daily arXiv Drag to adjust width of filter panel
let filterResizerInitialized = false;
function setupDailyArxivFilterResizing() {
    // Prevent repeated initialization
    if (filterResizerInitialized) {
        console.log('filterresizerAlready initialized');
        return;
    }

    const filterPanel = document.getElementById('daily-arxiv-filter-panel');
    const resizer = document.getElementById('daily-arxiv-filter-resizer');

    if (!filterPanel || !resizer) {
        console.warn('Filter panel or adjustment handle not found', { filterPanel, resizer });
        return;
    }

    // Check if element is visible
    const isVisible = filterPanel.offsetParent !== null;
    console.log('Whether the filter panel is visible:', isVisible, 'width:', filterPanel.offsetWidth);
    console.log('Resizerelement:', resizer, 'offsetWidth:', resizer.offsetWidth, 'offsetHeight:', resizer.offsetHeight);

    filterResizerInitialized = true;
    console.log('✅ Filter panel drag adjustment function has been initialized');

    let isResizing = false;
    let startX = 0;
    let startWidth = 0;

    // Add for testinghoverEffect
    resizer.addEventListener('mouseenter', () => {
        console.log('🖱️ mouse enterresizerarea');
    });

    resizer.addEventListener('mouseleave', () => {
        console.log('🖱️ mouse awayresizerarea');
    });

    // Prevent events from bubbling up
    resizer.addEventListener('mousedown', (e) => {
        isResizing = true;
        startX = e.clientX;
        startWidth = filterPanel.offsetWidth;
        resizer.classList.add('resizing');

        console.log('🔵 Start adjusting filter width:', startWidth, 'px, mouse position:', startX);

        // Prevent default behavior and event bubbling
        e.preventDefault();
        e.stopPropagation();

        // Add global styles to improve dragging experience
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;

        e.preventDefault();

        const deltaX = e.clientX - startX;
        const newWidth = startWidth + deltaX;

        // Limit minimum and maximum width
        const minWidth = 240;
        const maxWidth = 600;

        if (newWidth >= minWidth && newWidth <= maxWidth) {
            filterPanel.style.width = `${newWidth}px`;
        }
    });

    document.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            resizer.classList.remove('resizing');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';

            const finalWidth = filterPanel.style.width;
            console.log('✅ Adjustment completed, final width:', finalWidth);

            // save width to localStorage
            try {
                localStorage.setItem('dailyArxivFilterPanelWidth', finalWidth);
            } catch (e) {
                console.error('Failed to save filter panel width:', e);
            }
        }
    });

    // from localStorage restore width
    try {
        const savedWidth = localStorage.getItem('dailyArxivFilterPanelWidth');
        if (savedWidth) {
            filterPanel.style.width = savedWidth;
            console.log('📏 Restore filter width:', savedWidth);
        }
    } catch (e) {
        console.error('Failed to restore filter panel width:', e);
    }
}

// Stop all Daily arXiv Progress polling
function stopAllDailyArxivPolling() {
    Object.keys(dailyArxivProgressIntervals).forEach(category => {
        clearInterval(dailyArxivProgressIntervals[category]);
        delete dailyArxivProgressIntervals[category];
    });
}

// Check if there are partitions being fetched, if so start polling
async function checkAndStartProgressPolling() {
    // Only perform polling in Daily arXiv view
    const dailyArxivView = document.getElementById('daily-arxiv-view');
    if (!dailyArxivView || dailyArxivView.style.display === 'none') {
        return;
    }

    let hasActiveTask = false;

    // Check all partitions, start polling for all ongoing tasks
    for (const cat of dailyArxivCategories) {
        try {
            const res = await fetch(`/api/daily-arxiv/progress/${cat}`);
            if (res.ok) {
                const data = await res.json();
                const progress = data.progress;
                if (progress.status === 'fetching' || progress.status === 'processing') {
                    hasActiveTask = true;
                    // Start polling for this partition
                    startProgressPolling(cat);

                    // If the partition is the currently viewed partition（or"all"）, update the progress display immediately
                    if (dailyArxivCurrentCategory === 'all' || cat === dailyArxivCurrentCategory) {
                        updateProgressUI(cat, progress);

                        // If there are crawled papers, the display will be updated immediately
                        if (progress.papers && progress.papers.length > 0) {
                            // Application front-end standardization
                            const normalizedPapers = applyFrontendNormalizationToPapers(progress.papers);

                            // Update paper cache
                            normalizedPapers.forEach(paper => {
                                const paperDate = paper.announced
                                    ? paper.announced.split('T')[0]
                                    : dailyArxivCurrentDate;
                                const cacheKey = `${paperDate}_${cat}`;

                                if (!dailyArxivPapers[cacheKey]) {
                                    dailyArxivPapers[cacheKey] = [];
                                }

                                // Check if it already exists
                                const existingIndex = dailyArxivPapers[cacheKey].findIndex(
                                    p => p.arxiv_id === paper.arxiv_id
                                );

                                if (existingIndex >= 0) {
                                    // Update existing paper
                                    dailyArxivPapers[cacheKey][existingIndex] = paper;
                                } else {
                                    // Add new paper
                                    dailyArxivPapers[cacheKey].push(paper);
                                }
                            });

                            // Refresh grid display
                            renderDailyArxivGrid();
                        }
                    }
                }
            }
        } catch (err) {
            console.error(`examine ${cat} Progress failed:`, err);
        }
    }

    // If there are active tasks, refresh the list of available dates（Dates may have been added）
    if (hasActiveTask) {
        await loadAvailableDates();
    }
}

// Load list of available dates
async function loadAvailableDates() {
    try {
        const res = await fetch('/api/daily-arxiv/dates');
        if (res.ok) {
            const data = await res.json();
            if (data.enabled === false || !isDailyArxivEnabled()) {
                dailyArxivAvailableDates = [];
                dailyArxivCurrentDate = data.today || new Date().toISOString().split('T')[0];
                updateDateDisplay();
                updateDateNavButtons();
                setDailyArxivEmptyState('disabled');
                return;
            }

            dailyArxivAvailableDates = data.dates || [];
            const today = data.today;

            // By default, the latest date of the paper will be displayed, if not, today will be displayed.
            if (dailyArxivAvailableDates.length > 0) {
                dailyArxivCurrentDate = dailyArxivAvailableDates[0];  // latest date
            } else {
                dailyArxivCurrentDate = today;
                dailyArxivAvailableDates = [today];
            }

            updateDateDisplay();
            updateDateNavButtons();
        }
    } catch (err) {
        console.error('Failed to load available dates:', err);
    }
}

// Update date display
function updateDateDisplay() {
    const dateEl = document.getElementById('daily-arxiv-current-date');
    if (dateEl && dailyArxivCurrentDate) {
        const date = new Date(dailyArxivCurrentDate + 'T00:00:00');
        const options = { year: 'numeric', month: 'long', day: 'numeric', weekday: 'long' };
        dateEl.textContent = date.toLocaleDateString('en-US', options);
    }
}

// Update date navigation button state
function updateDateNavButtons() {
    const prevBtn = document.getElementById('daily-arxiv-prev-date');
    const nextBtn = document.getElementById('daily-arxiv-next-date');

    if (!dailyArxivAvailableDates.length) {
        if (prevBtn) prevBtn.disabled = true;
        if (nextBtn) nextBtn.disabled = true;
        return;
    }

    const currentIndex = dailyArxivAvailableDates.indexOf(dailyArxivCurrentDate);

    // The date list is in descending order（latest first）
    if (prevBtn) {
        prevBtn.disabled = currentIndex >= dailyArxivAvailableDates.length - 1;
    }
    if (nextBtn) {
        nextBtn.disabled = currentIndex <= 0;
    }
}

// date navigation
async function navigateDate(direction) {
    const currentIndex = dailyArxivAvailableDates.indexOf(dailyArxivCurrentDate);
    // direction: -1 means moving forward（Older），1 Indicates the future（renew）
    // The date list is in descending order, so -1 correspond index+1，1 correspond index-1
    const newIndex = currentIndex - direction;

    if (newIndex >= 0 && newIndex < dailyArxivAvailableDates.length) {
        dailyArxivCurrentDate = dailyArxivAvailableDates[newIndex];
        saveCurrentViewState();  // save state
        updateDateDisplay();
        updateDateNavButtons();

        // Load papers for this date（Even if there is a partition being crawled, you can switch to view other dates）
        await loadPapersForCurrentDate();

        // Check if there are partitions being crawled on the date you switched to
        if (dailyArxivCurrentCategory) {
            checkCategoryProgress(dailyArxivCurrentCategory);
        }
    }
}

// Load papers of current date
async function loadPapersForCurrentDate() {
    // Only load in Daily arXiv view
    const dailyArxivView = document.getElementById('daily-arxiv-view');
    if (!dailyArxivView || dailyArxivView.style.display === 'none') {
        return;
    }

    if (!dailyArxivCurrentDate) {
        return;
    }

    const emptyEl = document.getElementById('daily-arxiv-empty');
    const loadingEl = document.getElementById('daily-arxiv-loading');
    const gridEl = document.getElementById('daily-arxiv-grid');

    if (!isDailyArxivEnabled()) {
        setDailyArxivEmptyState('disabled');
        if (gridEl) gridEl.innerHTML = '';
        if (loadingEl) loadingEl.style.display = 'none';
        return;
    }
    setDailyArxivEmptyState('default');

    // Partitions have been configured and empty status prompts are hidden.
    if (dailyArxivCategories.length > 0 && emptyEl) {
        emptyEl.style.display = 'none';
    }

    // in the case of"all", load all partitions；Otherwise load the specified partition
    const categoriesToLoad = dailyArxivCurrentCategory === 'all'
        ? dailyArxivCategories
        : [dailyArxivCurrentCategory];

    let needsLoading = false;

    // Check if it needs to be loaded from the server
    for (const cat of categoriesToLoad) {
        const cacheKey = `${dailyArxivCurrentDate}_${cat}`;
        if (!dailyArxivPapers[cacheKey]) {
            needsLoading = true;
            break;
        }
    }

    if (needsLoading) {
        if (loadingEl) loadingEl.style.display = 'flex';

        try {
            // Load all required partitions
            await Promise.all(categoriesToLoad.map(async (cat) => {
                const cacheKey = `${dailyArxivCurrentDate}_${cat}`;
                if (!dailyArxivPapers[cacheKey]) {
                    const res = await fetch(`/api/daily-arxiv/papers/${dailyArxivCurrentDate}?category=${cat}`);
                    if (res.ok) {
                        const data = await res.json();
                        let papers = data.papers || [];
                        // Application front-end organization standardization
                        papers = applyFrontendNormalizationToPapers(papers);
                        dailyArxivPapers[cacheKey] = papers;
                    }
                }
            }));
        } catch (err) {
            console.error('Failed to load paper:', err);
        } finally {
            if (loadingEl) loadingEl.style.display = 'none';
        }
    }

    try {
        const arxivIds = [];
        categoriesToLoad.forEach(cat => {
            const cacheKey = `${dailyArxivCurrentDate}_${cat}`;
            const ps = dailyArxivPapers[cacheKey] || [];
            ps.forEach(p => {
                if (p && typeof p.arxiv_id === 'string' && p.arxiv_id.trim()) {
                    arxivIds.push(p.arxiv_id.trim());
                }
            });
        });
        await syncDailyArxivReadStatusFromServer(arxivIds);
    } catch (e) {
    }

    // After the paper data is loaded, first refresh the filter options and then render the grid.
    // Ensure that the institution mapping table is loaded (if not already loaded)
    if (!dailyArxivKnownInstitutions || dailyArxivKnownInstitutions.size === 0) {
        await loadKnownInstitutions();
    }
    renderDailyArxivFilterAffiliations();
    renderDailyArxivFilterCountries();
    renderDailyArxivFilterKeywords();
    renderDailyArxivGrid();
    renderDailyArxivCategoryTags();
}

// Auto save Daily arXiv set up（Anti-shake）
const autoSaveDailyArxivSettings = debounce(() => {
    saveDailyArxivSettings(true); // silent mode
}, 500);

// load Daily arXiv set up
async function loadDailyArxivSettings() {
    try {
        const res = await fetch('/api/settings/daily-arxiv');
        if (res.ok) {
            dailyArxivSettings = await res.json();
            dailyArxivCategories = dailyArxivSettings.categories || [];

            // Update settings panel values
            const enabledEl = document.getElementById('daily-arxiv-enabled');
            const retentionDaysEl = document.getElementById('daily-arxiv-retention-days');
            const checkIntervalEl = document.getElementById('daily-arxiv-check-interval');
            const maxKeywordsEl = document.getElementById('daily-arxiv-max-keywords');

            if (enabledEl) {
                enabledEl.checked = dailyArxivSettings.enabled === true; // Default to false
                enabledEl.addEventListener('change', autoSaveDailyArxivSettings);
            }

            if (retentionDaysEl) {
                retentionDaysEl.value = dailyArxivSettings.retentionDays || 7;
                retentionDaysEl.addEventListener('change', autoSaveDailyArxivSettings);
            }
            if (checkIntervalEl) {
                checkIntervalEl.value = dailyArxivSettings.checkIntervalMinutes || 10;
                checkIntervalEl.addEventListener('change', autoSaveDailyArxivSettings);
            }
            if (maxKeywordsEl) {
                maxKeywordsEl.value = dailyArxivSettings.maxKeywords || 1;
                maxKeywordsEl.addEventListener('change', autoSaveDailyArxivSettings);
            }

            renderDailyArxivCategoryTags();
            renderDailyArxivSettingsCategoryList();
            renderDailyArxivKeywordList();
            setDailyArxivEmptyState(isDailyArxivEnabled() ? 'default' : 'disabled');
        }

        // Load list of known institutions
        // Lazy loading: Only when the Daily arXiv function is enabled or when entering the Daily arXiv interface is it necessary to load
        const dailyArxivView = document.getElementById('daily-arxiv-view');
        if (isDailyArxivEnabled() && dailyArxivView && dailyArxivView.style.display !== 'none') {
            await loadKnownInstitutions();
        }
    } catch (err) {
        console.error('load Daily arXiv Setup failed:', err);
    }
}

// Load a list of all known institutions（System default + User defined）
async function loadKnownInstitutions() {
    // Avoid repeated loading
    if (dailyArxivKnownInstitutions && dailyArxivKnownInstitutions.size > 0) {
        return;
    }

    try {
        const res = await fetch('/api/all-known-institutions');
        if (res.ok) {
            const data = await res.json();
            if (data.success) {
                dailyArxivKnownInstitutions = new Set(data.institutions || []);
                console.log(`[DailyArxiv] Loaded ${dailyArxivKnownInstitutions.size} known institutions`);
            }
        }
    } catch (err) {
        console.error('Failed to load list of known institutions:', err);
    }
}

// keep Daily arXiv set up
async function saveDailyArxivSettings(silent = false) {
    try {
        const enabled = document.getElementById('daily-arxiv-enabled')?.checked;
        const retentionDays = parseInt(document.getElementById('daily-arxiv-retention-days')?.value) || 7;
        const checkInterval = parseInt(document.getElementById('daily-arxiv-check-interval')?.value) || 10;
        const maxKeywords = parseInt(document.getElementById('daily-arxiv-max-keywords')?.value) || 1;

        // Limit the maximum number of keywords to 1-3 within range
        const clampedMaxKeywords = Math.max(1, Math.min(3, maxKeywords));

        // Get keyword list（rendered fromDOMextracted from）
        const keywordList = [];
        const keywordItems = document.querySelectorAll('.daily-arxiv-keyword-item .keyword-text');
        keywordItems.forEach(item => {
            const keyword = item.textContent.trim();
            if (keyword) {
                keywordList.push(keyword);
            }
        });

        dailyArxivSettings.enabled = enabled;
        dailyArxivSettings.categories = dailyArxivCategories;
        dailyArxivSettings.retentionDays = retentionDays;
        dailyArxivSettings.checkIntervalMinutes = checkInterval;
        dailyArxivSettings.maxKeywords = clampedMaxKeywords;
        dailyArxivSettings.keywordList = keywordList;

        const res = await fetch('/api/settings/daily-arxiv', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(dailyArxivSettings)
        });

        if (res.ok) {
            if (!silent) {
                showMessage('Daily arXiv Settings saved', 'success');
            }
            renderDailyArxivCategoryTags();
        } else {
            showMessage('Failed to save settings', 'error');
        }
    } catch (err) {
        console.error('keep Daily arXiv Setup failed:', err);
        showMessage('Failed to save settings', 'error');
    }
}

// Add to arXiv Partition
function addDailyArxivCategory() {
    const input = document.getElementById('daily-arxiv-new-category');
    if (!input) return;

    const category = input.value.trim();
    if (!category) {
        showMessage('Please enter a partition name', 'warning');
        return;
    }

    if (dailyArxivCategories.includes(category)) {
        showMessage('The partition already exists', 'warning');
        return;
    }

    dailyArxivCategories.push(category);
    input.value = '';
    renderDailyArxivSettingsCategoryList();
    renderDailyArxivCategoryTags();
    // Auto save
    autoSaveDailyArxivSettings();
}

// Quickly add partitions
function addDailyArxivCategoryQuick(category) {
    if (dailyArxivCategories.includes(category)) {
        showMessage('The partition already exists', 'warning');
        return;
    }

    dailyArxivCategories.push(category);
    renderDailyArxivSettingsCategoryList();
    renderDailyArxivCategoryTags();
    // Auto save
    autoSaveDailyArxivSettings();
}

// Remove arXiv Partition
function removeDailyArxivCategory(category) {
    const index = dailyArxivCategories.indexOf(category);
    if (index > -1) {
        dailyArxivCategories.splice(index, 1);
        renderDailyArxivSettingsCategoryList();
        renderDailyArxivCategoryTags();
        // Auto save
        autoSaveDailyArxivSettings();
    }
}

// Partition list in render settings panel
function renderDailyArxivSettingsCategoryList() {
    const container = document.getElementById('daily-arxiv-category-list');
    if (!container) return;

    if (dailyArxivCategories.length === 0) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = dailyArxivCategories.map(cat => `
        <div class="daily-arxiv-category-item">
            <span>${cat}</span>
            <button class="remove-btn" onclick="removeDailyArxivCategory('${cat}')" title="Remove">
                <i class="fas fa-times"></i>
            </button>
        </div>
    `).join('');
}

// Render keyword list
function renderDailyArxivKeywordList() {
    const container = document.getElementById('daily-arxiv-keyword-list');
    if (!container) return;

    const keywordList = dailyArxivSettings.keywordList || [];

    if (keywordList.length === 0) {
        container.innerHTML = '<div style="color: #8b949e; font-size: 13px; padding: 8px;">There are no keywords yet, please add them in the input box below</div>';
        return;
    }

    container.innerHTML = keywordList.map((keyword, index) => {
        // Escape special characters to prevent XSS
        const escapedKeyword = keyword.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        const escapedKeywordForAttr = keyword.replace(/'/g, "\\'").replace(/"/g, '\\"');
        return `
        <div class="daily-arxiv-keyword-item" data-keyword="${escapedKeyword}">
            <span class="keyword-text">${keyword}</span>
            <button class="remove-keyword-btn" onclick="removeDailyArxivKeyword('${escapedKeywordForAttr}')" title="delete">
                <i class="fas fa-times"></i>
            </button>
        </div>
        `;
    }).join('');
}

// Add keywords
function addDailyArxivKeyword() {
    const input = document.getElementById('daily-arxiv-new-keyword');
    if (!input) return;

    const keyword = input.value.trim();
    if (!keyword) {
        showMessage('Please enter keywords', 'warning');
        return;
    }

    // make sure keywordList exist
    if (!dailyArxivSettings.keywordList) {
        dailyArxivSettings.keywordList = [];
    }

    if (dailyArxivSettings.keywordList.includes(keyword)) {
        showMessage('This keyword already exists', 'warning');
        input.value = '';
        return;
    }

    dailyArxivSettings.keywordList.push(keyword);
    input.value = '';
    renderDailyArxivKeywordList();
    // Auto save
    autoSaveDailyArxivSettings();
}

// Delete keywords
function removeDailyArxivKeyword(keyword) {
    if (!dailyArxivSettings.keywordList) {
        dailyArxivSettings.keywordList = [];
    }

    const index = dailyArxivSettings.keywordList.indexOf(keyword);
    if (index > -1) {
        dailyArxivSettings.keywordList.splice(index, 1);
        renderDailyArxivKeywordList();
        // Auto save
        autoSaveDailyArxivSettings();
    }
}

// Set keyword input box event
function setupDailyArxivKeywordInput() {
    const keywordInput = document.getElementById('daily-arxiv-new-keyword');
    if (!keywordInput) return;

    // Remove old event listener（if exists）
    const newKeywordInput = keywordInput.cloneNode(true);
    keywordInput.parentNode.replaceChild(newKeywordInput, keywordInput);

    // Bind carriage return event
    newKeywordInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            addDailyArxivKeyword();
        }
    });
}

// rendering Daily arXiv Interface partition label
function renderDailyArxivCategoryTags() {
    const container = document.getElementById('daily-arxiv-categories');
    if (!container) return;

    // Count the number of papers in each partition
    let allCount = 0;
    const categoryCounts = {};

    dailyArxivCategories.forEach(cat => {
        const cacheKey = `${dailyArxivCurrentDate}_${cat}`;
        const papers = dailyArxivPapers[cacheKey] || [];
        categoryCounts[cat] = papers.length;
        allCount += papers.length;
    });

    // Add to"all"Label
    const allTag = `
        <span class="daily-arxiv-category-tag ${dailyArxivCurrentCategory === 'all' ? 'active' : ''}" 
              onclick="switchDailyArxivCategory('all')"
              title="${allCount ? allCount + ' papers' : 'All partitions'}">
            all${allCount ? ' (' + allCount + ')' : ''}
        </span>
    `;

    // Generate individual partition labels
    const categoryTags = dailyArxivCategories.map(cat => {
        const isActive = cat === dailyArxivCurrentCategory;
        const count = categoryCounts[cat];
        return `
            <span class="daily-arxiv-category-tag ${isActive ? 'active' : ''}" 
                  onclick="switchDailyArxivCategory('${cat}')"
                  title="${count ? count + ' papers' : 'Click to load'}">
                ${cat}${count ? ' (' + count + ')' : ''}
            </span>
        `;
    }).join('');

    container.innerHTML = allTag + categoryTags;
}

// test LLM API（used for Daily arXiv Before crawling, reuse settings Interface testing logic）
async function testLLMAPIForDailyArxiv() {
    try {
        // Get current LLM Configuration
        const response = await fetch('/api/settings/agentic');
        const settings = await response.json();

        const cfg = getAgenticLLMConfig(settings, 'dailyArxiv');

        // Direct reuse testLLMAPICore function
        return await testLLMAPICore(cfg.llmModel, cfg.llmBaseUrl, cfg.llmApiKey, 'dailyArxiv');
    } catch (error) {
        return {
            success: false,
            error: `test failed: ${error.message}`
        };
    }
}

// Show rounded pop-up prompts（reference ti-item design, permanent display）
function showRoundedNotification(message, type = 'error', persistent = true, notificationId = 'daily-arxiv-api-notification', actionButton = null) {
    // If the notification already exists, only update the content
    let notification = document.getElementById(notificationId);

    if (notification) {
        // Update the content of an existing notification
        const messageSpan = notification.querySelector('span');
        if (messageSpan) {
            messageSpan.textContent = message;
        }
        // Update action button（If provided）
        if (actionButton) {
            const existingActionBtn = notification.querySelector('.notification-action-btn');
            if (existingActionBtn) {
                existingActionBtn.outerHTML = actionButton;
            } else {
                // Insert action button before close button
                const closeBtn = notification.querySelector('button[onclick*="remove"]');
                if (closeBtn) {
                    closeBtn.insertAdjacentHTML('beforebegin', actionButton);
                }
            }
        }
        return;
    }

    // Create notification element
    notification = document.createElement('div');
    notification.id = notificationId;
    notification.style.cssText = `
        position: fixed;
        top: 70px;
        right: 20px;
        z-index: 2000;
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 10px 16px;
        border-radius: 8px;
        font-weight: 500;
        font-size: 13px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        animation: slideInRight 0.3s ease-out;
        max-width: 400px;
    `;

    // Set styles based on type（reference ti-item design）
    if (type === 'error') {
        notification.style.background = '#fff5f5';
        notification.style.color = '#c62828';
        notification.style.border = '1px solid #ffcccb';
    } else if (type === 'warning') {
        notification.style.background = '#fff8e1';
        notification.style.color = '#9a7b00';
        notification.style.border = '1px solid #ffe08a';
    } else {
        notification.style.background = '#e7f3ff';
        notification.style.color = '#0b61c8';
        notification.style.border = '1px solid #9cc7ff';
    }

    notification.innerHTML = `
        <i class="fas fa-exclamation-triangle" style="font-size: 14px;"></i>
        <span>${message}</span>
        ${actionButton || ''}
        <button onclick="removeNotificationWithAnimation('${notificationId}')" style="
            background: none;
            border: none;
            color: inherit;
            cursor: pointer;
            padding: 0;
            margin-left: 8px;
            opacity: 0.7;
            font-size: 16px;
            line-height: 1;
            transition: opacity 0.2s;
        " onmouseover="this.style.opacity='1'" onmouseout="this.style.opacity='0.7'" title="closure">
            <i class="fas fa-times"></i>
        </button>
    `;

    // Add animation style（if not yet）
    if (!document.getElementById('daily-arxiv-notification-style')) {
        const style = document.createElement('style');
        style.id = 'daily-arxiv-notification-style';
        style.textContent = `
            @keyframes slideInRight {
                from {
                    transform: translateX(100%);
                    opacity: 0;
                }
                to {
                    transform: translateX(0);
                    opacity: 1;
                }
            }
            @keyframes slideOutRight {
                from {
                    transform: translateX(0);
                    opacity: 1;
                }
                to {
                    transform: translateX(100%);
                    opacity: 0;
                }
            }
        `;
        document.head.appendChild(style);
    }

    document.body.appendChild(notification);

    // if persistent for false，5Automatically removed after seconds
    if (!persistent) {
        setTimeout(() => {
            removeNotificationWithAnimation(notificationId);
        }, 5000);
    }
}

// Trigger crawling of papers（current partition）
async function triggerFetchPapers(force = false) {
    if (!isDailyArxivEnabled()) {
        showMessage('Daily arXiv is disabled in settings', 'warning');
        setDailyArxivEmptyState('disabled');
        return;
    }
    // examine LLM Configuration
    if (!dailyArxivLLMConfigured) {
        showRoundedNotification('Please configure it in settings first LLM API（Model、Base URL、API Key）', 'warning');
        // Switch to settings page
        switchTab('setting');
        // switch to Agentic settings panel
        setTimeout(() => {
            const agenticBtn = document.querySelector('[data-setting="agentic"]');
            if (agenticBtn) agenticBtn.click();
        }, 100);
        return;
    }

    if (dailyArxivCategories.length === 0) {
        showMessage('Please configure first arXiv Partition', 'warning');
        return;
    }

    if (!dailyArxivCurrentCategory) {
        dailyArxivCurrentCategory = dailyArxivCategories[0];
    }

    // Test before crawling LLM API
    const testResult = await testLLMAPIForDailyArxiv();
    if (!testResult.success) {
        const actionButton = `
            <button class="notification-action-btn" onclick="restartDailyArxivFetch()" style="
                background: #c62828;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 12px;
                font-size: 12px;
                cursor: pointer;
                margin-left: 8px;
                transition: background 0.2s;
            " onmouseover="this.style.background='#a02020'" onmouseout="this.style.background='#c62828'" title="Retest and start crawling">
                <i class="fas fa-redo"></i> Restart crawling
            </button>
        `;
        showRoundedNotification('LLM API Call failed, stop Daily arXiv,Check, please LLM API set up.', 'error', true, 'daily-arxiv-api-notification', actionButton);
        return;
    }

    try {
        // Trigger background crawl（Use the currently viewed date, or today's date if not available）
        const dateToFetch = dailyArxivCurrentDate || new Date().toISOString().split('T')[0];
        const res = await fetch('/api/daily-arxiv/fetch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                category: dailyArxivCurrentCategory,
                date: dateToFetch,
                force: force,
            })
        });

        const data = await res.json();

        if (data.success) {
            showMessage(`Start crawling ${dailyArxivCurrentCategory} paper...`, 'info');
            // Start polling progress
            startProgressPolling(dailyArxivCurrentCategory);
        } else {
            showMessage(data.error || 'Fetch failed', 'error');
        }
    } catch (err) {
        console.error('Failed to trigger crawl:', err);
        showMessage('Failed to trigger crawl', 'error');
    }
}

// Triggers crawling of papers in all partitions
async function triggerFetchAllCategories(force = false, dateStr = null) {
    if (!isDailyArxivEnabled()) {
        showMessage('Daily arXiv is disabled in settings', 'warning');
        setDailyArxivEmptyState('disabled');
        return;
    }
    // examine LLM Configuration
    if (!dailyArxivLLMConfigured) {
        showRoundedNotification('Please configure it in settings first LLM API（Model、Base URL、API Key）', 'warning');
        // Switch to settings page
        switchTab('setting');
        // switch to Agentic settings panel
        setTimeout(() => {
            const agenticBtn = document.querySelector('[data-setting="agentic"]');
            if (agenticBtn) agenticBtn.click();
        }, 100);
        return;
    }

    if (dailyArxivCategories.length === 0) {
        showMessage('Please configure first arXiv Partition', 'warning');
        return;
    }

    // Test before crawling LLM API
    const testResult = await testLLMAPIForDailyArxiv();
    if (!testResult.success) {
        const actionButton = `
            <button class="notification-action-btn" onclick="restartDailyArxivFetch()" style="
                background: #c62828;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 12px;
                font-size: 12px;
                cursor: pointer;
                margin-left: 8px;
                transition: background 0.2s;
            " onmouseover="this.style.background='#a02020'" onmouseout="this.style.background='#c62828'" title="Retest and start crawling">
                <i class="fas fa-redo"></i> Restart crawling
            </button>
        `;
        showRoundedNotification('LLM API Call failed, stop Daily arXiv,Check, please LLM API set up.', 'error', true, 'daily-arxiv-api-notification', actionButton);
        return;
    }

    try {
        // Trigger background crawl of all partitions（Use if a date is specified, otherwise use today's date）
        const dateToFetch = dateStr || new Date().toISOString().split('T')[0];
        const res = await fetch('/api/daily-arxiv/fetch-all', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                force: force,
                date: dateToFetch
            })
        });

        const data = await res.json();

        if (data.success) {
            showMessage(`Start crawling ${dailyArxivCategories.length} Papers on partitions...`, 'info');
            // Start independent progress polling for each partition
            dailyArxivCategories.forEach(cat => {
                startProgressPolling(cat);
            });
        } else {
            showMessage(data.error || 'Fetch failed', 'error');
        }
    } catch (err) {
        console.error('Failed to trigger crawl:', err);
        showMessage('Failed to trigger crawl', 'error');
    }
}

// Start progress polling（Manage each partition independently）
function startProgressPolling(category) {
    // If the partition is already polling, stop first
    if (dailyArxivProgressIntervals[category]) {
        clearInterval(dailyArxivProgressIntervals[category]);
    }

    let idleCount = 0;
    let inFlight = false;

    // Start polling
    dailyArxivProgressIntervals[category] = setInterval(async () => {
        if (inFlight) return;
        inFlight = true;
        try {
            const res = await fetch(`/api/daily-arxiv/progress/${category}`);
            if (res.ok) {
                const data = await res.json();
                const progress = data.progress;

                // if processing
                if (progress.status === 'fetching' || progress.status === 'processing') {
                    idleCount = 0;

                    // Currently selected partition or"all"update progress barUI
                    const shouldShowProgress = dailyArxivCurrentCategory === 'all' || category === dailyArxivCurrentCategory;
                    if (shouldShowProgress) {
                        const progressEl = document.getElementById('daily-arxiv-progress');
                        const loadingEl = document.getElementById('daily-arxiv-loading');
                        if (progressEl) progressEl.style.display = 'block';
                        if (loadingEl) loadingEl.style.display = 'none';
                        updateProgressUI(category, progress);

                        // Make sure to hide"No new papers yet"interface
                        const gridEl = document.getElementById('daily-arxiv-grid');
                        if (gridEl) {
                            const waitingEl = gridEl.querySelector('.daily-arxiv-waiting');
                            if (waitingEl) {
                                gridEl.innerHTML = '';
                            }
                        }
                    }

                    // Display crawled papers in real time（All partitions update data）
                    if (progress.papers && progress.papers.length > 0) {
                        let hasNewPaper = false;
                        let hasNewPaperForCurrentView = false;
                        const newDates = new Set();

                        progress.papers.forEach(paper => {
                            const paperDate = paper.announced
                                ? paper.announced.split('T')[0]
                                : dailyArxivCurrentDate;
                            const cacheKey = `${paperDate}_${category}`;

                            // debug log
                            if (!dailyArxivPapers[cacheKey] || !dailyArxivPapers[cacheKey].some(p => p.arxiv_id === paper.arxiv_id)) {
                                console.log(`[Daily arXiv] new paper: ${paper.title.substring(0, 50)}... | date: ${paperDate} | Partition: ${category} | 当前查看: ${dailyArxivCurrentDate}`);
                            }

                            // Record new date
                            if (paperDate && !dailyArxivAvailableDates.includes(paperDate)) {
                                newDates.add(paperDate);
                            }

                            if (!dailyArxivPapers[cacheKey]) {
                                dailyArxivPapers[cacheKey] = [];
                            }
                            const exists = dailyArxivPapers[cacheKey].some(p => p.arxiv_id === paper.arxiv_id);
                            if (!exists) {
                                dailyArxivPapers[cacheKey].push(paper);
                                hasNewPaper = true;
                                // Check if it is the currently viewed date and partition
                                const isCurrentDate = paperDate === dailyArxivCurrentDate;
                                const isCurrentCategory = dailyArxivCurrentCategory === 'all' || category === dailyArxivCurrentCategory;
                                if (isCurrentDate && isCurrentCategory) {
                                    hasNewPaperForCurrentView = true;
                                }
                            }
                        });

                        // Update list of available dates
                        if (newDates.size > 0) {
                            newDates.forEach(date => {
                                if (!dailyArxivAvailableDates.includes(date)) {
                                    dailyArxivAvailableDates.push(date);
                                }
                            });
                            // Reorder（Descending order, latest first）
                            dailyArxivAvailableDates.sort((a, b) => b.localeCompare(a));
                            updateDateNavButtons();
                        }

                        // Only new papers in the current section and date will be updated and displayed in real time.
                        if (hasNewPaperForCurrentView) {
                            renderDailyArxivGrid();
                        }

                        // Update all partition labels（Show number of papers）
                        if (hasNewPaper) {
                            renderDailyArxivCategoryTags();
                        }
                    }
                }

                // On completion or error, stop polling for this partition
                if (progress.status === 'done' || progress.status === 'error') {
                    stopProgressPolling(category);
                    await loadAvailableDates();
                    // If the current"all"Or this partition, refresh the display
                    if (dailyArxivCurrentCategory === 'all' || category === dailyArxivCurrentCategory) {
                        await loadPapersForCurrentDate();
                    }
                    // Update partition label display
                    renderDailyArxivCategoryTags();
                }

                // If idle, increment count
                if (progress.status === 'idle') {
                    idleCount++;
                    if (idleCount >= 3) {
                        stopProgressPolling(category);
                    }
                }
            }
        } catch (err) {
            console.error(`get ${category} Progress failed:`, err);
        } finally {
            inFlight = false;
        }
    }, 2500);
}

// Stop progress polling（Can stop specific partitions or all partitions）
function stopProgressPolling(category = null) {
    if (category) {
        // Stop specific partition
        if (dailyArxivProgressIntervals[category]) {
            clearInterval(dailyArxivProgressIntervals[category]);
            delete dailyArxivProgressIntervals[category];
        }

        // Reset the slow download prompt status of this partition
        delete dailyArxivSlowDownloadNotified[category];
        dailyArxivLastPaperKey = '';

        // Remove slow download prompt（if exists）
        const slowDownloadNotification = document.getElementById('daily-arxiv-slow-download-notification');
        if (slowDownloadNotification) {
            slowDownloadNotification.remove();
        }

        // If it is the current partition or"all", and no other partitions are crawling, hide the progress bar
        const shouldHideProgress = (dailyArxivCurrentCategory === 'all' || category === dailyArxivCurrentCategory)
            && Object.keys(dailyArxivProgressIntervals).length === 0;

        if (shouldHideProgress) {
            const progressEl = document.getElementById('daily-arxiv-progress');
            const loadingEl = document.getElementById('daily-arxiv-loading');

            if (loadingEl) loadingEl.style.display = 'none';
            if (progressEl) {
                setTimeout(() => {
                    progressEl.style.display = 'none';
                }, 1000);
            }
        }
    } else {
        // Stop all partitions
        Object.keys(dailyArxivProgressIntervals).forEach(cat => {
            clearInterval(dailyArxivProgressIntervals[cat]);
        });
        dailyArxivProgressIntervals = {};

        // Reset slow download prompt status for all partitions
        dailyArxivSlowDownloadNotified = {};
        dailyArxivLastPaperKey = '';

        // Remove slow download prompt（if exists）
        const slowDownloadNotification = document.getElementById('daily-arxiv-slow-download-notification');
        if (slowDownloadNotification) {
            slowDownloadNotification.remove();
        }

        const progressEl = document.getElementById('daily-arxiv-progress');
        const loadingEl = document.getElementById('daily-arxiv-loading');

        if (loadingEl) loadingEl.style.display = 'none';
        if (progressEl) {
            setTimeout(() => {
                progressEl.style.display = 'none';
            }, 1000);
        }
    }
}

// update progress UI
function updateProgressUI(category, progress) {
    const titleEl = document.getElementById('daily-arxiv-progress-title');
    const countEl = document.getElementById('daily-arxiv-progress-count');
    const barEl = document.getElementById('daily-arxiv-progress-bar');
    const currentEl = document.getElementById('daily-arxiv-progress-current');

    if (titleEl) titleEl.textContent = `Fetching ${category} paper...`;
    if (countEl) countEl.textContent = `${progress.current}/${progress.total}`;

    const percent = progress.total > 0 ? (progress.current / progress.total * 100) : 0;
    if (barEl) barEl.style.width = `${percent}%`;

    // Track the current paper and use it to detect paper switching
    const currentPaperKey = `${category}_${progress.current_paper || ''}`;
    const lastPaperKey = dailyArxivLastPaperKey || '';

    // If the paper is switched, reset the slow download prompt status and remove the prompt
    if (currentPaperKey !== lastPaperKey && lastPaperKey) {
        delete dailyArxivSlowDownloadNotified[category];
        // Remove slow download prompt（if exists）
        const slowDownloadNotification = document.getElementById('daily-arxiv-slow-download-notification');
        if (slowDownloadNotification) {
            slowDownloadNotification.remove();
        }
    }
    dailyArxivLastPaperKey = currentPaperKey;

    if (currentEl) {
        if (progress.current_paper) {
            // Format elapsed time
            const elapsedSeconds = progress.current_paper_elapsed_seconds || 0;
            let timeText = '';
            if (elapsedSeconds < 60) {
                timeText = `${elapsedSeconds}Second`;
            } else if (elapsedSeconds < 3600) {
                const minutes = Math.floor(elapsedSeconds / 60);
                const seconds = elapsedSeconds % 60;
                timeText = `${minutes}m ${seconds}s`;
            } else {
                const hours = Math.floor(elapsedSeconds / 3600);
                const minutes = Math.floor((elapsedSeconds % 3600) / 60);
                timeText = `${hours}Hour${minutes}minute`;
            }

            // Format file size
            const pdfSizeBytes = progress.current_paper_pdf_size || 0;
            let sizeText = '';
            if (pdfSizeBytes > 0) {
                if (pdfSizeBytes < 1024) {
                    sizeText = `${pdfSizeBytes} B`;
                } else if (pdfSizeBytes < 1024 * 1024) {
                    sizeText = `${(pdfSizeBytes / 1024).toFixed(1)} KB`;
                } else {
                    sizeText = `${(pdfSizeBytes / (1024 * 1024)).toFixed(2)} MB`;
                }
            }

            // Truncate overly long titles
            const maxTitleLength = 50;
            let paperTitle = progress.current_paper;
            if (paperTitle.length > maxTitleLength) {
                paperTitle = paperTitle.substring(0, maxTitleLength) + '...';
            }

            // Build display text
            let displayText = `Downloading: ${paperTitle} (Elapsed time: ${timeText})`;
            if (sizeText) {
                displayText += ` | ${sizeText}`;
            }
            currentEl.textContent = displayText;

            // Check if the download time exceeds30Second
            if (elapsedSeconds > 30 && !dailyArxivSlowDownloadNotified[category]) {
                // Show slow download prompt（Use standalone notificationsID, avoid comparing withLLM APIFailure prompt conflict）
                showRoundedNotification('The paper is too long to download from arXiv. Please check the proxy settings.', 'warning', true, 'daily-arxiv-slow-download-notification');
                dailyArxivSlowDownloadNotified[category] = true;
            }
        } else {
            currentEl.textContent = '';
            // If there is no current paper, reset the slow download prompt status and remove the prompt
            delete dailyArxivSlowDownloadNotified[category];
            const slowDownloadNotification = document.getElementById('daily-arxiv-slow-download-notification');
            if (slowDownloadNotification) {
                slowDownloadNotification.remove();
            }
        }
    }

    // Make sure the progress bar is hidden when shown"No new papers yet"interface
    const progressEl = document.getElementById('daily-arxiv-progress');
    if (progressEl && progressEl.style.display !== 'none') {
        // hide"No new papers yet"interface（by clearing grid content）
        const gridEl = document.getElementById('daily-arxiv-grid');
        if (gridEl) {
            // Check whether the displayed"No new papers yet"interface
            const waitingEl = gridEl.querySelector('.daily-arxiv-waiting');
            if (waitingEl) {
                gridEl.innerHTML = '';
            }
        }
    }
}


// get Daily arXiv paper（from cache or server）
async function fetchDailyArxivPapers(forceRefresh = false) {
    const loadingEl = document.getElementById('daily-arxiv-loading');
    const emptyEl = document.getElementById('daily-arxiv-empty');
    const gridEl = document.getElementById('daily-arxiv-grid');

    // Only displays empty status if no partition is configured
    if (dailyArxivCategories.length === 0) {
        if (loadingEl) loadingEl.style.display = 'none';
        if (emptyEl) emptyEl.style.display = 'flex';
        if (gridEl) gridEl.innerHTML = '';
        return;
    }

    // Partitions have been configured and empty status prompts are hidden.
    if (emptyEl) emptyEl.style.display = 'none';

    // If no partition is selected, select the first one
    if (!dailyArxivCurrentCategory) {
        dailyArxivCurrentCategory = dailyArxivCategories[0];
    }

    const cacheKey = `${dailyArxivCurrentDate}_${dailyArxivCurrentCategory}`;

    // If there is already data in the cache and no forced refresh is required, it will be displayed directly.
    if (!forceRefresh && dailyArxivPapers[cacheKey] && dailyArxivPapers[cacheKey].length > 0) {
        renderDailyArxivGrid();
        renderDailyArxivCategoryTags();
        return;
    }

    // Load from server
    await loadPapersForCurrentDate();
}

// switch partition
async function switchDailyArxivCategory(category) {
    dailyArxivCurrentCategory = category;
    saveCurrentViewState();  // save state
    renderDailyArxivCategoryTags();

    // load this partition（or all partitions）thesis
    await loadPapersForCurrentDate();

    // Check whether the partition is being crawled, and if so, display a progress bar
    if (category !== 'all') {
        checkCategoryProgress(category);
    } else {
        // Check all partitions
        dailyArxivCategories.forEach(cat => {
            checkCategoryProgress(cat);
        });
    }
}

// Check partition progress status
async function checkCategoryProgress(category) {
    try {
        const res = await fetch(`/api/daily-arxiv/progress/${category}`);
        if (res.ok) {
            const data = await res.json();
            const progress = data.progress;

            // If the partition is being crawled, display a progress bar
            if (progress.status === 'fetching' || progress.status === 'processing') {
                const progressEl = document.getElementById('daily-arxiv-progress');
                const loadingEl = document.getElementById('daily-arxiv-loading');
                if (progressEl) progressEl.style.display = 'block';
                if (loadingEl) loadingEl.style.display = 'none';
                updateProgressUI(category, progress);

                // Make sure to hide"No new papers yet"interface
                const gridEl = document.getElementById('daily-arxiv-grid');
                if (gridEl) {
                    const waitingEl = gridEl.querySelector('.daily-arxiv-waiting');
                    if (waitingEl) {
                        gridEl.innerHTML = '';
                    }
                }
            }
        }
    } catch (err) {
        console.error(`examine ${category} Progress failed:`, err);
    }
}

// Get the current view Daily arXiv Paper list
// applyFilters: Whether to apply the current filter conditions（Unit etc.）；The filter panel itself is passed in false to get complete data
function getCurrentDailyArxivPapers(applyFilters = true) {
    // Get original paper list: if yes "all", merge all partitions；Otherwise, only get the specified partition
    let papers = [];
    if (dailyArxivCurrentCategory === 'all') {
        dailyArxivCategories.forEach(cat => {
            const cacheKey = `${dailyArxivCurrentDate}_${cat}`;
            const catPapers = dailyArxivPapers[cacheKey] || [];
            papers = papers.concat(catPapers);
        });
    } else {
        const cacheKey = `${dailyArxivCurrentDate}_${dailyArxivCurrentCategory}`;
        papers = dailyArxivPapers[cacheKey] || [];
    }

    // exist "all" view, press arxiv_id Remove duplicates and merge tags from different partitions
    if (dailyArxivCurrentCategory === 'all' && papers.length > 0) {
        const mergedMap = new Map();

        papers.forEach(paper => {
            const key = paper.arxiv_id || `${paper.title || ''}__${paper.pdf_url || ''}`;
            if (!mergedMap.has(key)) {
                const cloned = { ...paper };
                const initialCat = paper.fetch_category || paper.primary_category || null;
                cloned.all_fetch_categories = initialCat ? [initialCat] : [];
                mergedMap.set(key, cloned);
            } else {
                const existing = mergedMap.get(key);
                const newCat = paper.fetch_category || paper.primary_category || null;
                if (newCat && !existing.all_fetch_categories.includes(newCat)) {
                    existing.all_fetch_categories.push(newCat);
                }
            }
        });

        papers = Array.from(mergedMap.values());
    }

    // application"first unit"filter
    if (applyFilters && dailyArxivFilterFirstAffiliation) {
        papers = papers.filter(paper => {
            const affs = paper.affiliations || [];
            // Keep only the first unit（if any）
            return affs.length > 0;
        });
    }

    // Apply unit filtering: If there are units selected, only keep affiliations Contains papers from any selected unit
    if (applyFilters && dailyArxivSelectedAffiliations.size > 0) {
        const selected = new Set(dailyArxivSelectedAffiliations);
        papers = papers.filter(paper => {
            const affs = paper.affiliations || [];
            // if enabled"first unit"Filter to check only the first unit
            if (dailyArxivFilterFirstAffiliation && affs.length > 0) {
                return selected.has(affs[0]);
            }
            return affs.some(aff => selected.has(aff));
        });
    }

    // Apply unit exclusion filter: Exclude papers containing excluded units
    if (applyFilters && dailyArxivExcludedAffiliations.size > 0) {
        const excluded = new Set(dailyArxivExcludedAffiliations);
        papers = papers.filter(paper => {
            const affs = paper.affiliations || [];
            return !affs.some(aff => excluded.has(aff));
        });
    }

    // Apply region filtering: If there is a selected region, only keep countries Contains papers from any selected region
    if (applyFilters && dailyArxivSelectedCountries.size > 0) {
        const selected = new Set(dailyArxivSelectedCountries);
        papers = papers.filter(paper => {
            const countries = paper.countries || [];
            return countries.some(country => {
                if (!country) return false;
                // Use standardized region names for comparison
                const normalizedCountry = normalizeCountryName(country);
                return selected.has(normalizedCountry);
            });
        });
    }

    // Apply region exclusion filter: Exclude papers containing excluded regions
    if (applyFilters && dailyArxivExcludedCountries.size > 0) {
        const excluded = new Set(dailyArxivExcludedCountries);
        papers = papers.filter(paper => {
            const countries = paper.countries || [];
            return !countries.some(country => {
                if (!country) return false;
                // Use standardized region names for comparison
                const normalizedCountry = normalizeCountryName(country);
                return excluded.has(normalizedCountry);
            });
        });
    }

    // Hide the first unit belongs to"Other institutions"Papers:
    // That is, papers whose first unit exists and is not in the list of known institutions will be filtered out.
    if (applyFilters && dailyArxivHideUnknownFirstAffiliation && dailyArxivKnownInstitutions.size > 0) {
        papers = papers.filter(paper => {
            const affs = paper.affiliations || [];
            if (affs.length === 0) return true; // If there is no institutional information, it will not be processed.
            const firstAff = affs[0];
            // Reserved if first unit is a known institution；Otherwise regarded as"Other institutions"and hide
            return dailyArxivKnownInstitutions.has(firstAff);
        });
    }

    // Apply keyword filtering: If there are selected keywords, only keep keywords Papers containing any of the selected keywords
    if (applyFilters && dailyArxivSelectedKeywords.size > 0) {
        const selected = new Set(dailyArxivSelectedKeywords);
        papers = papers.filter(paper => {
            const keywords = paper.keywords || [];
            return keywords.some(keyword => keyword && selected.has(keyword.trim()));
        });
    }

    // Apply keyword exclusion filter: exclude papers containing excluded keywords
    if (applyFilters && dailyArxivExcludedKeywords.size > 0) {
        const excluded = new Set(dailyArxivExcludedKeywords);
        papers = papers.filter(paper => {
            const keywords = paper.keywords || [];
            return !keywords.some(keyword => keyword && excluded.has(keyword.trim()));
        });
    }

    // Apply search filter: on title、authors、affiliations、abstract Search in
    if (applyFilters && dailyArxivSearchQuery && dailyArxivSearchQuery.trim()) {
        const q = dailyArxivSearchQuery.trim().toLowerCase();
        papers = papers.filter(paper => {
            // title
            const title = (paper.title || '').toLowerCase();
            if (title.includes(q)) return true;

            // authors
            const authors = (paper.authors || '').toLowerCase();
            if (authors.includes(q)) return true;

            // affiliations（mechanism）
            const affs = (paper.affiliations || []).join(' ').toLowerCase();
            if (affs.includes(q)) return true;

            // abstract
            const abstract = (paper.abstract || '').toLowerCase();
            if (abstract.includes(q)) return true;

            return false;
        });
    }

    return [...papers].sort((a, b) => {
        const readA = isDailyArxivPaperRead(a.arxiv_id) ? 1 : 0;
        const readB = isDailyArxivPaperRead(b.arxiv_id) ? 1 : 0;
        if (readA !== readB) return readA - readB;
        const timeA = a.published ? new Date(a.published).getTime() : 0;
        const timeB = b.published ? new Date(b.published).getTime() : 0;
        return timeB - timeA;
    });
}

// Get the list of papers used for keyword filtering statistics:
// - Based on current view（date & Partition）
// - Apply "First Unit" / mechanism / "Region" filters and exclusions
// - Do not apply filtering and exclusion of keywords themselves（Avoid self-influence）
function getDailyArxivPapersForKeywordFilter() {
    // First get the results without applying any filtering conditions but with deduplication/List of merged papers
    let papers = getCurrentDailyArxivPapers(false);

    // application"first unit"filter
    if (dailyArxivFilterFirstAffiliation) {
        papers = papers.filter(paper => {
            const affs = paper.affiliations || [];
            return affs.length > 0;
        });
    }

    // Apply unit selection filter
    if (dailyArxivSelectedAffiliations.size > 0) {
        const selected = new Set(dailyArxivSelectedAffiliations);
        papers = papers.filter(paper => {
            const affs = paper.affiliations || [];
            if (dailyArxivFilterFirstAffiliation && affs.length > 0) {
                return selected.has(affs[0]);
            }
            return affs.some(aff => selected.has(aff));
        });
    }

    // Apply organization exclusion filter
    if (dailyArxivExcludedAffiliations.size > 0) {
        const excluded = new Set(dailyArxivExcludedAffiliations);
        papers = papers.filter(paper => {
            const affs = paper.affiliations || [];
            return !affs.some(aff => excluded.has(aff));
        });
    }

    // Apply region selection filter
    if (dailyArxivSelectedCountries.size > 0) {
        const selected = new Set(dailyArxivSelectedCountries);
        papers = papers.filter(paper => {
            const countries = paper.countries || [];
            return countries.some(country => {
                if (!country) return false;
                const normalizedCountry = normalizeCountryName(country);
                return selected.has(normalizedCountry);
            });
        });
    }

    // Apply region exclusion filter
    if (dailyArxivExcludedCountries.size > 0) {
        const excluded = new Set(dailyArxivExcludedCountries);
        papers = papers.filter(paper => {
            const countries = paper.countries || [];
            return !countries.some(country => {
                if (!country) return false;
                const normalizedCountry = normalizeCountryName(country);
                return excluded.has(normalizedCountry);
            });
        });
    }

    // Hide the first unit belongs to"Other institutions"thesis（same getCurrentDailyArxivPapers logic in）
    if (dailyArxivHideUnknownFirstAffiliation && dailyArxivKnownInstitutions.size > 0) {
        papers = papers.filter(paper => {
            const affs = paper.affiliations || [];
            if (affs.length === 0) return true;
            const firstAff = affs[0];
            return dailyArxivKnownInstitutions.has(firstAff);
        });
    }

    return papers;
}

// Rendering thesis grid
function renderDailyArxivGrid() {
    const gridEl = document.getElementById('daily-arxiv-grid');
    const emptyEl = document.getElementById('daily-arxiv-empty');

    if (!gridEl) return;

    // Restore the grid's default layout style before each rendering
    gridEl.classList.remove('daily-arxiv-grid-no-results');

    // Get the papers in the current view（Sorted by time and in "all" Go down the view and merge the labels）
    const papers = getCurrentDailyArxivPapers();

    if (papers.length === 0) {
        // Check if there are active filters or search criteria
        const hasActiveFilters =
            dailyArxivFilterFirstAffiliation ||
            dailyArxivSelectedAffiliations.size > 0 ||
            dailyArxivExcludedAffiliations.size > 0 ||
            dailyArxivSelectedCountries.size > 0 ||
            dailyArxivExcludedCountries.size > 0 ||
            dailyArxivSelectedKeywords.size > 0 ||
            dailyArxivExcludedKeywords.size > 0 ||
            (dailyArxivSearchQuery && dailyArxivSearchQuery.trim().length > 0);

        // If there is filtering/The search criteria resulted in no papers, displayed"No matching search results"
        if (hasActiveFilters) {
            // Change the entire grid area to a centered layout
            gridEl.classList.add('daily-arxiv-grid-no-results');
            gridEl.innerHTML = `
                <div class="daily-arxiv-no-results">
                    <i class="fas fa-filter fa-3x" style="margin-bottom: 20px; color: #bbb;"></i>
                    <h3 style="margin-bottom: 10px; font-size: 1.5em; color: #555;">No matching search results</h3>
                    <p style="font-size: 1em; color: #888;">Please try adjusting your search terms or filters</p>
                </div>
            `;
            if (emptyEl) emptyEl.style.display = 'none';
            return;
        }

        // Check if any partitions are being crawled
        const isFetching = dailyArxivCurrentCategory === 'all'
            ? Object.keys(dailyArxivProgressIntervals).length > 0
            : dailyArxivProgressIntervals[dailyArxivCurrentCategory] !== undefined;

        // Check whether the progress bar is displayed（If there is a progress bar displayed, it means that the crawling is in progress and should not be displayed."No new papers yet"）
        const progressEl = document.getElementById('daily-arxiv-progress');
        const isProgressVisible = progressEl && progressEl.style.display !== 'none';

        // If there is a configuration partition but no paper
        if (dailyArxivCategories.length > 0) {
            // If crawling is in progress or the progress bar is displayed, the display is blank（Waiting for the paper to appear）
            if (isFetching || isProgressVisible) {
                gridEl.innerHTML = '';
            } else {
                // No longer crawling, check if there are papers on other dates
                const today = new Date().toISOString().split('T')[0];
                const isToday = dailyArxivCurrentDate === today;
                const hasOtherDates = dailyArxivAvailableDates.length > 1 || (dailyArxivAvailableDates.length === 1 && dailyArxivAvailableDates[0] !== today);

                let hint = '';
                if (isToday && hasOtherDates) {
                    hint = '<p style="margin-top: 15px; font-size: 0.9em; color: #2196F3;"><i class="fas fa-info-circle"></i> Tip: Click on the date navigation above to view historical papers</p>';
                }

                // show"Waiting"hint
                // Add class to make grid Container centered
                gridEl.classList.add('daily-arxiv-grid-no-results');

                // examine LLM Configuration
                if (!dailyArxivLLMConfigured) {
                    gridEl.innerHTML = `
                        <div class="daily-arxiv-waiting" style="display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 400px; text-align: center; color: #666; width: 100%;">
                            <i class="fas fa-exclamation-triangle fa-3x" style="margin-bottom: 20px; color: #f39c12;"></i>
                            <h3 style="margin-bottom: 10px; font-size: 1.5em; color: #555;">LLM API Not configured</h3>
                            <p style="margin-bottom: 30px; font-size: 1em; color: #888;">Daily arXiv needs to be configured with LLM API. Please configure in settings LLM API（Model、Base URL、API Key）</p>
                            <div style="display: flex; gap: 10px; flex-wrap: wrap; justify-content: center;">
                                <button class="btn btn-primary" onclick="switchTab('setting'); setTimeout(() => { const btn = document.querySelector('[data-setting=\\'agentic\\']'); if (btn) btn.click(); }, 100);">
                                    <i class="fas fa-cog"></i> Go to settings
                                </button>
                            </div>
                        </div>
                    `;
                } else {
                    gridEl.innerHTML = `
                        <div class="daily-arxiv-waiting" style="display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 400px; text-align: center; color: #666; width: 100%;">
                            <i class="fas fa-clock fa-3x" style="margin-bottom: 20px; color: #999;"></i>
                            <h3 style="margin-bottom: 10px; font-size: 1.5em; color: #555;">No new papers yet</h3>
                            <p style="margin-bottom: 30px; font-size: 1em; color: #888;">Wait for automatic fetching, or click the button below to trigger manually</p>
                            <div style="display: flex; gap: 10px; flex-wrap: wrap; justify-content: center;">
                                <button class="btn btn-primary" onclick="triggerFetchPapers(false)">
                                    <i class="fas fa-sync"></i> Grab the current partition
                                </button>
                                <button class="btn btn-secondary" onclick="triggerFetchAllCategories(false)">
                                    <i class="fas fa-sync-alt"></i> Fetch all partitions
                                </button>
                            </div>
                            ${hint}
                        </div>
                    `;
                }
            }
            if (emptyEl) emptyEl.style.display = 'none';
        } else {
            // No partitions are configured and configuration prompts are displayed.
            gridEl.innerHTML = '';
            if (emptyEl) emptyEl.style.display = 'flex';
        }
        return;
    }

    if (emptyEl) emptyEl.style.display = 'none';

    gridEl.innerHTML = papers.map((paper, index) => {
        const isRead = isDailyArxivPaperRead(paper.arxiv_id);
        // use announced date（Announcement date）instead of published（Submission date）
        const date = paper.announced
            ? new Date(paper.announced).toLocaleDateString('en-US')
            : (paper.updated ? new Date(paper.updated).toLocaleDateString('en-US') : '');
        const authors = paper.authors ? (paper.authors.length > 50 ? paper.authors.substring(0, 50) + '...' : paper.authors) : '';

        // Organization information display（Complete display, gray rounded border, different colors for different units）
        let affiliationsHtml = '';
        if (paper.affiliations && paper.affiliations.length > 0) {
            const affTags = paper.affiliations.map(aff => {
                const color = getColorForString(aff);
                return `<span class="aff-mini-tag" style="color: ${color};">${escapeHtml(aff)}</span>`;
            }).join('');
            affiliationsHtml = `<div class="daily-arxiv-card-affiliations">
                ${affTags}
            </div>`;
        }

        // Region flag display（To remove duplicates, use set）- Will be displayed in the upper left corner of the image, to the right of the category label
        let countriesFlagsHtml = '';
        if (paper.countries && paper.countries.length > 0) {
            const uniqueCountries = [...new Set(paper.countries.filter(c => c && c.trim()))];
            if (uniqueCountries.length > 0) {
                const flagTags = uniqueCountries.map(country => {
                    const flag = getCountryFlag(country);
                    return flag ? `<span class="country-flag-in-thumbnail" title="${escapeHtml(country)}">${flag}</span>` : '';
                }).filter(tag => tag).join('');
                if (flagTags) {
                    countriesFlagsHtml = `<div class="daily-arxiv-card-countries-thumbnail">${flagTags}</div>`;
                }
            }
        }

        // Calculate classification labels for display:
        // - Give priority to using the merged all_fetch_categories
        // - Otherwise fall back to a single fetch_category / current partition / Main category of paper
        let categoryTags = [];
        if (Array.isArray(paper.all_fetch_categories) && paper.all_fetch_categories.length > 0) {
            categoryTags = paper.all_fetch_categories;
        } else if (paper.fetch_category) {
            categoryTags = [paper.fetch_category];
        } else if (dailyArxivCurrentCategory && dailyArxivCurrentCategory !== 'all') {
            categoryTags = [dailyArxivCurrentCategory];
        } else if (paper.primary_category) {
            categoryTags = [paper.primary_category];
        }
        const displayCategoryLabel = categoryTags.join(', ');

        // for thumbnails API The classification parameters still only take one specific partition to avoid illegal paths.
        const thumbnailCategory = categoryTags[0] || paper.fetch_category || paper.primary_category || dailyArxivCurrentCategory || '';

        // Keyword display（Below the date, in black font, use LLM raw output）
        let keywordsHtml = '';
        if (paper.keywords && paper.keywords.length > 0) {
            // Sort by keyword length in ascending order（Put the shortest one first to save space）
            const sortedKeywords = [...paper.keywords].sort((a, b) => a.length - b.length);
            const kwTags = sortedKeywords.map(kw => {
                // Use original keywords directly without case conversion
                return `<span class="keyword-mini-tag">${escapeHtml(kw)}</span>`;
            }).join('');
            keywordsHtml = `<div class="daily-arxiv-card-keywords">${kwTags}</div>`;
        }

        // Generate thumbnailsURL
        let thumbnailHtml = '';
        if (paper.thumbnail_path) {
            // fromthumbnail_pathExtract information to buildURL
            // thumbnail_pathFormat: /path/to/date/category/arxiv_id_thumbnail.jpg
            const thumbnailUrl = `/api/daily-arxiv/thumbnail/${dailyArxivCurrentDate}/${encodeURIComponent(thumbnailCategory)}/${encodeURIComponent(paper.arxiv_id)}`;
            thumbnailHtml = `
                <img src="${thumbnailUrl}" 
                     loading="lazy"
                     alt="${escapeHtml(paper.title)}" 
                     onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';"
                     style="width: 100%; height: 100%; object-fit: cover;" />
                <div class="thumbnail-fallback" style="display: none; width: 100%; height: 100%; align-items: center; justify-content: center; background: #f5f5f5;">
                    <i class="fas fa-file-pdf placeholder-icon"></i>
                </div>
            `;
        } else {
            thumbnailHtml = `
                <i class="fas fa-file-pdf placeholder-icon"></i>
            `;
        }

        // Highlight function: only highlight the title when there is a search term/author/Institutions do <mark> pack
        const highlight = (text) => highlightDailyArxiv(text);

        return `
            <div class="daily-arxiv-card ${isRead ? 'read' : ''}" data-index="${index}" onclick="showDailyArxivDetail(${index})">
                <div class="daily-arxiv-card-thumbnail">
                    ${thumbnailHtml}
                    <div class="daily-arxiv-card-thumbnail-badges">
                        <span class="daily-arxiv-card-category">${displayCategoryLabel}</span>
                        ${countriesFlagsHtml}
                    </div>
                </div>
                <div class="daily-arxiv-card-body">
                    <div class="daily-arxiv-card-title" title="${escapeHtml(paper.title)}">${highlight(paper.title)}</div>
                    <div class="daily-arxiv-card-authors" title="${escapeHtml(paper.authors)}">${highlight(authors)}</div>
                    ${paper.affiliations && paper.affiliations.length > 0 ? `
                        <div class="daily-arxiv-card-affiliations">
                            ${paper.affiliations.map(aff => {
            const color = getColorForString(aff);
            return `<span class="aff-mini-tag" style="color: ${color};">${highlight(aff)}</span>`;
        }).join('')}
                        </div>
                    ` : ''}
                    <div class="daily-arxiv-card-meta">
                        <span class="daily-arxiv-card-date">${date}</span>
                        <div class="daily-arxiv-card-actions">
                            ${paper.homepage ? `<button class="daily-arxiv-card-action" onclick="event.stopPropagation(); window.open('${paper.homepage.startsWith('http') ? paper.homepage : 'https://' + paper.homepage}', '_blank')" title="Project home page">
                                <i class="fas fa-home"></i>
                            </button>` : ''}
                            ${paper.github ? `<button class="daily-arxiv-card-action" onclick="event.stopPropagation(); window.open('${paper.github.startsWith('http') ? paper.github : 'https://' + paper.github}', '_blank')" title="GitHub storehouse">
                                <i class="fab fa-github"></i>
                            </button>` : ''}
                            <button class="daily-arxiv-card-action" onclick="event.stopPropagation(); window.open('https://arxiv.org/abs/${paper.arxiv_id}', '_blank')" title="exist arXiv Check">
                                <i class="fas fa-external-link-alt"></i>
                            </button>
                            ${(() => {
                // Check if the paper is on the to-read list
                const isInReadingList = paper.paper_id && readingListPaperIds.has(paper.paper_id);
                if (isInReadingList) {
                    return `<button class="daily-arxiv-card-action add-to-reading-list paper-col-btn reading icon-only in-list" data-paper-id="${paper.paper_id}" onclick="onDailyArxivRemoveFromReadingList(${index}, event)" title="Remove from to-read list">
                                        <i class="fas fa-times"></i>
                                    </button>`;
                } else {
                    return `<button class="daily-arxiv-card-action add-to-reading-list paper-col-btn reading icon-only" onclick="onDailyArxivAddToReadingList(${index}, event)" title="Add to Readling List">
                                        <i class="fas fa-book-open"></i>
                                    </button>`;
                }
            })()}
                        </div>
                    </div>
                    ${keywordsHtml}
                </div>
            </div>
        `;
    }).join('');
}

// Render unit filter
function renderDailyArxivFilterAffiliations() {
    const container = document.getElementById('daily-arxiv-filter-affiliations');
    if (!container) return;

    // Calculate unit statistics based on the paper in the current view（No units applied/Regional filtering, but will consider"first unit"Configuration）
    const papers = getCurrentDailyArxivPapers(false);
    const stats = new Map(); // aff -> { count, color, isKnown }

    // Count the number of first units（Used to display the total）
    let firstAffCount = 0;
    // Count the number of common institutions（Used to display the total）
    let knownInstCount = 0;

    papers.forEach(paper => {
        const affs = paper.affiliations || [];
        if (affs.length > 0) {
            firstAffCount++;

            // Check if there are common institutions
            if (affs.some(aff => dailyArxivKnownInstitutions.has(aff))) {
                knownInstCount++;
            }
        }

        // Determine which institutions are counted based on special filter conditions
        let affsToCount = affs;

        // if enabled"first unit"Filter to only count the first institution
        if (dailyArxivFilterFirstAffiliation && affs.length > 0) {
            affsToCount = [affs[0]];
        }

        affsToCount.forEach(aff => {
            if (!aff) return;
            const key = aff;
            const isKnown = dailyArxivKnownInstitutions.has(aff);

            if (!stats.has(key)) {
                stats.set(key, { count: 1, color: getColorForString(key), isKnown });
            } else {
                stats.get(key).count += 1;
            }
        });
    });

    const entries = Array.from(stats.entries());
    // Just clear it when there are no units
    if (entries.length === 0) {
        container.innerHTML = '<span class="filter-empty">There is currently no institution information in the current view</span>';
        return;
    }

    // Grouping: Common Institutions vs Other institutions
    const knownEntries = entries.filter(([aff, info]) => info.isKnown);
    const unknownEntries = entries.filter(([aff, info]) => !info.isKnown);

    // Sort by quantity in descending order, then by name
    const sortFn = (a, b) => {
        const countDiff = b[1].count - a[1].count;
        if (countDiff !== 0) return countDiff;
        return a[0].localeCompare(b[0]);
    };
    knownEntries.sort(sortFn);
    unknownEntries.sort(sortFn);

    // generate HTML:Special filter items + Common institutions + Other institutions
    let html = '';

    // Special filter items
    html += `
        <div class="daily-arxiv-filter-special-items">
            <button 
                class="daily-arxiv-filter-special ${dailyArxivFilterFirstAffiliation ? 'active' : ''}" 
                onclick="toggleFirstAffiliationFilter()"
                title="Show only papers with first unit">
                <span class="label">first unit</span>
                <span class="count">(${firstAffCount})</span>
            </button>
        </div>
    `;

    // Determines whether to display group titles
    // If there are two institutions, the group title will be displayed.
    const shouldShowGroupTitles = knownEntries.length > 0 && unknownEntries.length > 0;

    // List of common institutions
    if (knownEntries.length > 0) {
        if (shouldShowGroupTitles) {
            html += '<div class="filter-section-divider">Common institutions</div>';
        }
        html += knownEntries.map(([aff, info]) => {
            const isSelected = dailyArxivSelectedAffiliations.has(aff);
            const isExcluded = dailyArxivExcludedAffiliations.has(aff);
            const countLabel = info.count > 1 ? ` (${info.count})` : '';
            const bgColor = getBgColorForString(aff);
            const textColor = info.color;
            const activeClass = isSelected ? 'active' : '';
            const excludedClass = isExcluded ? 'excluded' : '';
            return `
                <button 
                    class="daily-arxiv-filter-affiliation ${activeClass} ${excludedClass}" 
                    data-affiliation="${escapeHtml(aff)}"
                    title="${escapeHtml(aff)}${countLabel}"
                    style="${!isExcluded ? `border-color: ${textColor}; color: ${textColor}; background: ${isSelected ? bgColor : 'transparent'};` : ''}"
                >
                    <span class="dot" style="background:${isExcluded ? '#9ca3af' : textColor};"></span>
                    <span class="label">${escapeHtml(aff)}</span>
                    ${countLabel}
                    <span class="filter-remove-btn" onclick="event.stopPropagation(); toggleExcludeAffiliation('${escapeHtml(aff).replace(/'/g, "\\'")}');" title="Exclude this organization">
                        <i class="fas fa-times"></i>
                    </span>
                </button>
            `;
        }).join('');
    }

    // List of other institutions
    if (unknownEntries.length > 0) {
        if (shouldShowGroupTitles) {
            html += `
                <div class="filter-section-divider">
                    <span>Other institutions</span>
                    <button 
                        class="hide-all-unknown-btn ${dailyArxivHideUnknownFirstAffiliation ? 'active' : ''}" 
                        onclick="hideAllUnknownInstitutions()" 
                        title="Hide the first unit belongs to「Other institutions」thesis；Click again to unhide">
                        Hide all
                    </button>
                </div>
            `;
        }
        html += unknownEntries.map(([aff, info]) => {
            const isSelected = dailyArxivSelectedAffiliations.has(aff);
            const isManuallyExcluded = dailyArxivExcludedAffiliations.has(aff);
            // When the global "Hide All" is turned on, this group itself represents "other institutions" and should also appear visually excluded.
            const isEffectivelyExcluded = isManuallyExcluded || dailyArxivHideUnknownFirstAffiliation;
            const countLabel = info.count > 1 ? ` (${info.count})` : '';
            const bgColor = getBgColorForString(aff);
            const textColor = info.color;
            const activeClass = isSelected ? 'active' : '';
            const excludedClass = isEffectivelyExcluded ? 'excluded' : '';
            const style = !isEffectivelyExcluded
                ? 'border-color: ' + textColor + '; color: ' + textColor + '; background: ' + (isSelected ? bgColor : 'transparent') + ';'
                : '';
            return `
                <button 
                    class="daily-arxiv-filter-affiliation ${activeClass} ${excludedClass}" 
                    data-affiliation="${escapeHtml(aff)}"
                    title="${escapeHtml(aff)}${countLabel}"
                    style="${style}"
                >
                    <span class="dot" style="background:${isEffectivelyExcluded ? '#9ca3af' : textColor};"></span>
                    <span class="label">${escapeHtml(aff)}</span>
                    ${countLabel}
                    <span class="filter-remove-btn" onclick="event.stopPropagation(); toggleExcludeAffiliation('${escapeHtml(aff).replace(/'/g, "\\'")}');" title="Exclude this organization">
                        <i class="fas fa-times"></i>
                    </span>
                </button>
            `;
        }).join('');
    }

    container.innerHTML = html;

    // Bind click event（Multiple choice）
    container.querySelectorAll('.daily-arxiv-filter-affiliation').forEach(btn => {
        btn.addEventListener('click', (e) => {
            // If the click is x button, does not trigger selection
            if (e.target.closest('.filter-remove-btn')) return;

            const aff = btn.getAttribute('data-affiliation');
            if (!aff) return;
            // If it has been excluded, cancel the exclusion first
            if (dailyArxivExcludedAffiliations.has(aff)) {
                dailyArxivExcludedAffiliations.delete(aff);
            }
            if (dailyArxivSelectedAffiliations.has(aff)) {
                dailyArxivSelectedAffiliations.delete(aff);
            } else {
                dailyArxivSelectedAffiliations.add(aff);
            }
            // Re-render filters and grids for real-time filtering
            renderDailyArxivFilterAffiliations();
            renderDailyArxivFilterKeywords();
            renderDailyArxivGrid();
        });
    });
}

// Render region filter
function renderDailyArxivFilterCountries() {
    const container = document.getElementById('daily-arxiv-filter-countries');
    if (!container) return;

    // Calculate regional statistics based on papers in the current view（Do not apply region filtering）
    const papers = getCurrentDailyArxivPapers(false);
    const stats = new Map(); // normalized country name -> count

    papers.forEach(paper => {
        const countries = paper.countries || [];
        countries.forEach(country => {
            if (!country || !country.trim()) return;
            // Use standardized region names askey
            const normalizedCountry = normalizeCountryName(country);
            if (!stats.has(normalizedCountry)) {
                stats.set(normalizedCountry, 1);
            } else {
                stats.set(normalizedCountry, stats.get(normalizedCountry) + 1);
            }
        });
    });

    const entries = Array.from(stats.entries());
    // Just clear it if there is no region
    if (entries.length === 0) {
        container.innerHTML = '<span class="filter-empty">There is currently no region information in the current view</span>';
        return;
    }

    // Sort by quantity in descending order, then by name
    entries.sort((a, b) => {
        const countDiff = b[1] - a[1];
        if (countDiff !== 0) return countDiff;
        return a[0].localeCompare(b[0]);
    });

    container.innerHTML = entries.map(([country, count]) => {
        const isSelected = dailyArxivSelectedCountries.has(country);
        const isExcluded = dailyArxivExcludedCountries.has(country);
        // Try to get the flag, if not found try to use the original country name（before standardization）
        let flag = getCountryFlag(country);
        // If you still can't find it, try some common variations
        if (!flag) {
            // Try adding common suffixes/Variations of prefix
            const variants = [
                country,
                country.replace(/\s+Republic\s*$/i, ''),
                country.replace(/\s+Kingdom\s*$/i, ''),
                country.replace(/^The\s+/i, ''),
                country.replace(/\s+of\s+.*$/i, ''),
            ];
            for (const variant of variants) {
                flag = getCountryFlag(variant);
                if (flag) break;
            }
        }
        const countLabel = count > 1 ? ` (${count})` : '';
        const activeClass = isSelected ? 'active' : '';
        const excludedClass = isExcluded ? 'excluded' : '';

        // If there is no flag, display the abbreviation or simplified name
        let displayText = flag;
        if (!flag) {
            // Try to generate abbreviation（Capitalize the first letter）
            const words = country.split(/\s+/).filter(w => w.length > 0);
            if (words.length > 1 && words.length <= 4) {
                // If there are multiple words, use the abbreviation
                displayText = words.map(w => w[0].toUpperCase()).join('');
            } else if (country.length > 15) {
                // If too long, truncate
                displayText = country.substring(0, 12) + '...';
            } else {
                displayText = country;
            }
        }

        return `
            <button 
                class="daily-arxiv-filter-affiliation ${activeClass} ${excludedClass}" 
                data-country="${escapeHtml(country)}"
                title="${escapeHtml(country)}${countLabel}"
                style="${!isExcluded ? '' : ''}"
            >
                <span class="dot" style="background:transparent;"></span>
                <span class="label country-flag-label ${flag ? '' : 'no-flag'}">${escapeHtml(displayText)}</span>
                ${countLabel}
                <span class="filter-remove-btn" onclick="event.stopPropagation(); toggleExcludeCountry('${escapeHtml(country).replace(/'/g, "\\'")}');" title="exclude this region">
                    <i class="fas fa-times"></i>
                </span>
            </button>
        `;
    }).join('');

    // Bind click event（Multiple choice）
    container.querySelectorAll('.daily-arxiv-filter-affiliation').forEach(btn => {
        btn.addEventListener('click', (e) => {
            // If the click is x button, does not trigger selection
            if (e.target.closest('.filter-remove-btn')) return;

            const country = btn.getAttribute('data-country');
            if (!country) return;
            // If it has been excluded, cancel the exclusion first
            if (dailyArxivExcludedCountries.has(country)) {
                dailyArxivExcludedCountries.delete(country);
            }
            if (dailyArxivSelectedCountries.has(country)) {
                dailyArxivSelectedCountries.delete(country);
            } else {
                dailyArxivSelectedCountries.add(country);
            }
            // Re-render filters and grids for real-time filtering
            renderDailyArxivFilterCountries();
            renderDailyArxivFilterKeywords();
            renderDailyArxivGrid();
        });
    });
}

// Toggle unit exclusion status
// switch"first unit"filter
function toggleFirstAffiliationFilter() {
    dailyArxivFilterFirstAffiliation = !dailyArxivFilterFirstAffiliation;
    renderDailyArxivFilterAffiliations();
    renderDailyArxivFilterKeywords();
    renderDailyArxivGrid();
}

function hideAllUnknownInstitutions() {
    // Use as a switch:
    // - First click: Turn on the filter of "Hide the first unit as other institutions"
    // - Click again: Close this filter and restore the display of all papers
    dailyArxivHideUnknownFirstAffiliation = !dailyArxivHideUnknownFirstAffiliation;

    // Re-render
    renderDailyArxivFilterAffiliations();
    renderDailyArxivFilterKeywords();
    renderDailyArxivGrid();
}

function toggleExcludeAffiliation(aff) {
    if (!aff) return;
    // If it is selected, uncheck it first
    if (dailyArxivSelectedAffiliations.has(aff)) {
        dailyArxivSelectedAffiliations.delete(aff);
    }
    // Toggle exclusion status
    if (dailyArxivExcludedAffiliations.has(aff)) {
        dailyArxivExcludedAffiliations.delete(aff);
    } else {
        dailyArxivExcludedAffiliations.add(aff);
    }
    renderDailyArxivFilterAffiliations();
    renderDailyArxivFilterKeywords();
    renderDailyArxivGrid();
}

// Toggle region exclusion status
function toggleExcludeCountry(country) {
    if (!country) return;
    // If it is selected, uncheck it first
    if (dailyArxivSelectedCountries.has(country)) {
        dailyArxivSelectedCountries.delete(country);
    }
    // Toggle exclusion status
    if (dailyArxivExcludedCountries.has(country)) {
        dailyArxivExcludedCountries.delete(country);
    } else {
        dailyArxivExcludedCountries.add(country);
    }
    renderDailyArxivFilterCountries();
    renderDailyArxivFilterKeywords();
    renderDailyArxivGrid();
}

// Render keyword filter
function renderDailyArxivFilterKeywords() {
    const container = document.getElementById('daily-arxiv-filter-keywords');
    if (!container) return;

    // Calculate keyword statistics based on the papers in the current view:
    // - The currently selected unit will be taken into account/Region filtering
    // - Filtering on the keyword itself will not be applied（avoid influencing each other）
    const papers = getDailyArxivPapersForKeywordFilter();
    const stats = new Map(); // keyword -> count

    papers.forEach(paper => {
        const keywords = paper.keywords || [];
        keywords.forEach(keyword => {
            if (!keyword || !keyword.trim()) return;
            const key = keyword.trim();
            if (!stats.has(key)) {
                stats.set(key, 1);
            } else {
                stats.set(key, stats.get(key) + 1);
            }
        });
    });

    const entries = Array.from(stats.entries());
    // Just clear it when there are no keywords
    if (entries.length === 0) {
        container.innerHTML = '<span class="filter-empty">There is currently no keyword information in the current view</span>';
        return;
    }

    // Sort by quantity in descending order, then by name
    entries.sort((a, b) => {
        const countDiff = b[1] - a[1];
        if (countDiff !== 0) return countDiff;
        return a[0].localeCompare(b[0]);
    });

    container.innerHTML = entries.map(([keyword, count]) => {
        const isSelected = dailyArxivSelectedKeywords.has(keyword);
        const isExcluded = dailyArxivExcludedKeywords.has(keyword);
        const countLabel = count > 1 ? ` (${count})` : '';
        const activeClass = isSelected ? 'active' : '';
        const excludedClass = isExcluded ? 'excluded' : '';
        return `
            <button 
                class="daily-arxiv-filter-affiliation ${activeClass} ${excludedClass}" 
                data-keyword="${escapeHtml(keyword)}"
                title="${escapeHtml(keyword)}${countLabel}"
                style="${!isExcluded ? '' : ''}"
            >
                <span class="dot" style="background:transparent;"></span>
                <span class="label">${escapeHtml(keyword)}</span>
                ${countLabel}
                <span class="filter-remove-btn" onclick="event.stopPropagation(); toggleExcludeKeyword('${escapeHtml(keyword).replace(/'/g, "\\'")}');" title="Exclude this keyword">
                    <i class="fas fa-times"></i>
                </span>
            </button>
        `;
    }).join('');

    // Bind click event（Multiple choice）
    container.querySelectorAll('.daily-arxiv-filter-affiliation').forEach(btn => {
        btn.addEventListener('click', (e) => {
            // If the click is x button, does not trigger selection
            if (e.target.closest('.filter-remove-btn')) return;

            const keyword = btn.getAttribute('data-keyword');
            if (!keyword) return;
            // If it has been excluded, cancel the exclusion first
            if (dailyArxivExcludedKeywords.has(keyword)) {
                dailyArxivExcludedKeywords.delete(keyword);
            }
            if (dailyArxivSelectedKeywords.has(keyword)) {
                dailyArxivSelectedKeywords.delete(keyword);
            } else {
                dailyArxivSelectedKeywords.add(keyword);
            }
            // Re-render filters and grids for real-time filtering
            renderDailyArxivFilterKeywords();
            renderDailyArxivGrid();
        });
    });
}

// Switch keyword exclusion status
function toggleExcludeKeyword(keyword) {
    if (!keyword) return;
    // If it is selected, uncheck it first
    if (dailyArxivSelectedKeywords.has(keyword)) {
        dailyArxivSelectedKeywords.delete(keyword);
    }
    // Toggle exclusion status
    if (dailyArxivExcludedKeywords.has(keyword)) {
        dailyArxivExcludedKeywords.delete(keyword);
    } else {
        dailyArxivExcludedKeywords.add(keyword);
    }
    renderDailyArxivFilterKeywords();
    renderDailyArxivGrid();
}

// HTML escape
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Show paper details
function showDailyArxivDetail(index) {
    // Get the list of currently displayed papers（and renderDailyArxivGrid Logic remains consistent, including merge logic）
    const papers = getCurrentDailyArxivPapers();
    const paper = papers[index];
    if (!paper) return;
    if (markDailyArxivPaperRead(paper.arxiv_id)) {
        dailyArxivRerenderAfterDetailClose = true;
    }

    // use announced date（Announcement date）
    const announcedDate = paper.announced
        ? new Date(paper.announced).toLocaleDateString('en-US')
        : '';
    const submitDate = paper.published ? new Date(paper.published).toLocaleDateString('en-US') : '';

    // Institutional information area（with color）
    let affiliationsHtml = '';
    if (paper.affiliations && paper.affiliations.length > 0) {
        const affTags = paper.affiliations.map(aff => {
            const bgColor = getBgColorForString(aff);
            const textColor = getColorForString(aff);
            return `<span class="affiliation-tag" style="background: ${bgColor}; color: ${textColor};">${escapeHtml(aff)}</span>`;
        }).join('');

        // Region flag display（Remove duplicates）
        let countriesFlagsHtml = '';
        if (paper.countries && paper.countries.length > 0) {
            const uniqueCountries = [...new Set(paper.countries.filter(c => c && c.trim()))];
            if (uniqueCountries.length > 0) {
                const flagTags = uniqueCountries.map(country => {
                    const flag = getCountryFlag(country);
                    return flag ? `<span class="country-flag-large" title="${escapeHtml(country)}">${flag}</span>` : '';
                }).filter(tag => tag).join('');
                if (flagTags) {
                    countriesFlagsHtml = `<div class="country-flags-section">
                        <span class="country-flags-label">Regions:</span>
                        <div class="country-flags">${flagTags}</div>
                    </div>`;
                }
            }
        }

        affiliationsHtml = `
            <div class="daily-arxiv-detail-affiliations">
                <h4><i class="fas fa-building"></i> Affiliations</h4>
                <div class="affiliation-tags">${affTags}</div>
                ${countriesFlagsHtml}
            </div>
        `;
    } else {
        affiliationsHtml = `
            <div class="daily-arxiv-detail-affiliations">
                <h4><i class="fas fa-building"></i> Affiliations</h4>
                <div class="affiliation-extract-prompt">
                    <p>Institutional information has not been extracted yet</p>
                    <button class="btn btn-secondary btn-sm" onclick="extractAffiliationsForPaper(${index})">
                        <i class="fas fa-magic"></i> Extract organization information
                    </button>
                </div>
            </div>
        `;
    }

    // keyword area（Black font, use LLM raw output）
    let keywordsHtml = '';
    if (paper.keywords && paper.keywords.length > 0) {
        // Sort by keyword length in ascending order（The shortest one comes first）
        const sortedKeywords = [...paper.keywords].sort((a, b) => a.length - b.length);
        const kwTags = sortedKeywords.map(kw => {
            // Use original keywords directly without case conversion
            return `<span class="keyword-tag">${escapeHtml(kw)}</span>`;
        }).join('');
        keywordsHtml = `
            <div class="daily-arxiv-detail-keywords">
                <h4><i class="fas fa-key"></i> Keywords</h4>
                <div class="keyword-tags">${kwTags}</div>
            </div>
        `;
    }

    // summary summary area（show first summary, then display abstract）
    let summaryHtml = '';
    if (paper.summary) {
        summaryHtml = `
            <div class="daily-arxiv-detail-summary">
                <h4><i class="fas fa-lightbulb"></i> Brief summary</h4>
                <p>${escapeHtml(paper.summary)}</p>
            </div>
        `;
    }

    const modalHtml = `
        <div class="daily-arxiv-detail-modal" onclick="if(event.target === this) closeDailyArxivDetail()">
            <div class="daily-arxiv-detail-content">
                <div class="daily-arxiv-detail-header">
                    <h3>${escapeHtml(paper.title)}</h3>
                    <button class="daily-arxiv-detail-close" onclick="closeDailyArxivDetail()">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
                <div class="daily-arxiv-detail-body">
                    <div class="daily-arxiv-detail-meta">
                        <div class="daily-arxiv-detail-meta-item">
                            <i class="fas fa-users"></i>
                            <span>${escapeHtml(paper.authors)}</span>
                        </div>
                        <div class="daily-arxiv-detail-meta-item">
                            <i class="fas fa-tag"></i>
                            <span>${(paper.categories || []).join(', ')}</span>
                        </div>
                        <div class="daily-arxiv-detail-meta-item">
                            <i class="fas fa-calendar"></i>
                            <span>Announce: ${announcedDate} | submit: ${submitDate}</span>
                        </div>
                        ${paper.homepage ? `<div class="daily-arxiv-detail-meta-item">
                            <i class="fas fa-home"></i>
                            <span><a href="${paper.homepage.startsWith('http') ? paper.homepage : 'https://' + paper.homepage}" target="_blank" style="color: #2196F3; text-decoration: none;">${escapeHtml(paper.homepage)}</a></span>
                        </div>` : ''}
                        ${paper.github ? `<div class="daily-arxiv-detail-meta-item">
                            <i class="fab fa-github"></i>
                            <span><a href="${paper.github.startsWith('http') ? paper.github : 'https://' + paper.github}" target="_blank" style="color: #2196F3; text-decoration: none;">${escapeHtml(paper.github)}</a></span>
                        </div>` : ''}
                    </div>
                    ${affiliationsHtml}
                    ${keywordsHtml}
                    ${summaryHtml}
                    <div class="daily-arxiv-detail-abstract">
                        <h4><i class="fas fa-file-alt"></i> Abstract</h4>
                        <p>${escapeHtml(paper.abstract)}</p>
                    </div>
                </div>
                <div class="daily-arxiv-detail-footer">
                    <div class="daily-arxiv-detail-links">
                        ${paper.homepage ? `<a href="${paper.homepage.startsWith('http') ? paper.homepage : 'https://' + paper.homepage}" target="_blank" title="Project home page">
                            <i class="fas fa-home"></i> Homepage
                        </a>` : ''}
                        ${paper.github ? `<a href="${paper.github.startsWith('http') ? paper.github : 'https://' + paper.github}" target="_blank" title="GitHub storehouse">
                            <i class="fab fa-github"></i> GitHub
                        </a>` : ''}
                        <a href="https://arxiv.org/abs/${paper.arxiv_id}" target="_blank">
                            <i class="fas fa-external-link-alt"></i> arXiv
                        </a>
                        <a href="${paper.pdf_url}" target="_blank">
                            <i class="fas fa-file-pdf"></i> PDF
                        </a>
                    </div>
                    <button class="daily-arxiv-add-btn" onclick="onDailyArxivAddToReadingList(${index}, event); closeDailyArxivDetail();">
                        <i class="fas fa-book-open"></i> Add to Readling List
                    </button>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHtml);
}

// Close paper details
function closeDailyArxivDetail() {
    const modal = document.querySelector('.daily-arxiv-detail-modal');
    if (modal) {
        modal.remove();
    }
    if (dailyArxivRerenderAfterDetailClose) {
        dailyArxivRerenderAfterDetailClose = false;
        renderDailyArxivGrid();
    }
}

// Extract paper institution information
async function extractAffiliationsForPaper(paperIndex) {
    // Get the list of currently displayed papers（and renderDailyArxivGrid Logic remains consistent, including merge logic）
    const papers = getCurrentDailyArxivPapers();
    const paper = papers[paperIndex];
    if (!paper) return;

    // get Agentic Settings in LLM Configuration
    let agenticSettings = {};
    try {
        const res = await fetch('/api/settings/agentic');
        if (res.ok) {
            agenticSettings = await res.json();
        }
    } catch (err) {
        console.error('get Agentic Settings fail:', err);
    }

    const llmBaseUrl = agenticSettings.llmBaseUrl;
    const llmApiKey = agenticSettings.llmApiKey;

    if (!llmBaseUrl || !llmApiKey) {
        showMessage('Please configure it in settings first Agentic Settings of LLM API', 'warning');
        return;
    }

    // Update button state
    const extractBtn = document.querySelector('.affiliation-extract-prompt button');
    if (extractBtn) {
        extractBtn.disabled = true;
        extractBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Extracting...';
    }

    try {
        // Get the date and section information of a paper
        const paperDate = paper.fetch_date || dailyArxivCurrentDate;
        const paperCategory = paper.fetch_category || dailyArxivCurrentCategory;

        const res = await fetch('/api/daily-arxiv/extract-affiliations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                arxiv_id: paper.arxiv_id,
                date: paperDate,
                fetch_category: paperCategory,
            })
        });

        const data = await res.json();

        if (data.success) {
            // Update local cache（Use the correct cache key）
            const cacheKey = dailyArxivCurrentCategory === 'all'
                ? null  // All modes need to find the corresponding cache
                : `${dailyArxivCurrentDate}_${dailyArxivCurrentCategory}`;

            if (cacheKey && dailyArxivPapers[cacheKey]) {
                // Find the corresponding paper and update it
                const cachedPaper = dailyArxivPapers[cacheKey].find(p => p.arxiv_id === paper.arxiv_id);
                if (cachedPaper) {
                    cachedPaper.affiliations = data.affiliations || [];
                    cachedPaper.countries = data.countries || [];
                    cachedPaper.homepage = data.homepage || null;
                    cachedPaper.github = data.github || null;
                    cachedPaper.affiliations_extracted = true;
                }
            } else if (dailyArxivCurrentCategory === 'all') {
                // All mode: Need to find and update in the cache of all partitions
                dailyArxivCategories.forEach(cat => {
                    const catCacheKey = `${dailyArxivCurrentDate}_${cat}`;
                    if (dailyArxivPapers[catCacheKey]) {
                        const cachedPaper = dailyArxivPapers[catCacheKey].find(p => p.arxiv_id === paper.arxiv_id);
                        if (cachedPaper) {
                            cachedPaper.affiliations = data.affiliations || [];
                            cachedPaper.countries = data.countries || [];
                            cachedPaper.homepage = data.homepage || null;
                            cachedPaper.github = data.github || null;
                            cachedPaper.affiliations_extracted = true;
                        }
                    }
                });
            }

            // Refresh details modal box
            closeDailyArxivDetail();
            showDailyArxivDetail(paperIndex);

            // Refresh grid display
            renderDailyArxivGrid();

            const msgParts = [];
            if (data.affiliations && data.affiliations.length > 0) {
                msgParts.push(`Extract to ${data.affiliations.length} institutions`);
            }
            if (data.homepage) {
                msgParts.push('Extract to Homepage');
            }
            if (data.github) {
                msgParts.push('Extract to GitHub');
            }

            if (msgParts.length > 0) {
                showMessage(msgParts.join('，'), 'success');
            } else {
                showMessage('Failed to extract organization information,homepage or github', 'info');
            }
        } else {
            showMessage(data.error || 'Failed to extract organization information', 'error');
            // restore button
            if (extractBtn) {
                extractBtn.disabled = false;
                extractBtn.innerHTML = '<i class="fas fa-magic"></i> Extract organization information';
            }
        }
    } catch (err) {
        console.error('Failed to extract organization information:', err);
        const errorMsg = err.message || 'Failed to extract organization information, please check the network connection andAPIConfiguration';
        showMessage(errorMsg, 'error');
        // restore button
        if (extractBtn) {
            extractBtn.disabled = false;
            extractBtn.innerHTML = '<i class="fas fa-magic"></i> Extract organization information';
        }
    }
}

// Daily arXiv: Add to Readling List with one click（No pop-ups）
function onDailyArxivAddToReadingList(paperIndex, event) {
    if (event) {
        event.stopPropagation();
    }

    // Add directly to the to-read list with one click（Do not pop up the pop-up window for selecting a category）
    // 1. Get the list of currently displayed papers（and renderDailyArxivGrid Logic remains consistent, including merge logic）
    const papers = getCurrentDailyArxivPapers();
    const paper = papers[paperIndex];
    if (!paper) return;

    // 2. Use the temporary directory of the to-read list without selecting a category
    // 3. Call the backend: first import into the temporary directory, then add to the to-be-read list
    (async () => {
        try {
            // Use the crawl partition of the paper itself；If the current view is "all", don't put "all" Pass to backend
            const fetchCategory =
                paper.fetch_category ||
                (dailyArxivCurrentCategory === 'all' ? null : dailyArxivCurrentCategory);

            const body = {
                arxiv_id: paper.arxiv_id,
                use_temp_dir: true,  // Use temporary directory
                date: dailyArxivCurrentDate,
            };
            if (fetchCategory) {
                body.fetch_category = fetchCategory;
            }

            const res = await fetch('/api/daily-arxiv/add-to-library', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            const data = await res.json();

            if (!data.success) {
                showMessage(data.error || 'Add failed', 'error');
                return;
            }

            // After successful import, add it to the to-read list
            if (data.paper_id) {
                try {
                    const readingRes = await fetch(`/api/reading-list/${data.paper_id}/add`, {
                        method: 'POST',
                    });
                    if (!readingRes.ok) {
                        console.warn('Failed to add to to-read list:', await readingRes.text());
                    } else {
                        await updateReadingListCount();

                        // Update the current card button to a purple button that says "Remove from to-read list"
                        const card = document.querySelector(`.daily-arxiv-card[data-index="${paperIndex}"]`);
                        if (card) {
                            const btn = card.querySelector('.daily-arxiv-card-action.add-to-reading-list');
                            if (btn) {
                                btn.dataset.paperId = data.paper_id;
                                btn.title = 'Remove from to-read list';
                                btn.innerHTML = '<i class="fas fa-times"></i>';
                                btn.classList.add('in-list');
                                btn.onclick = (e) => onDailyArxivRemoveFromReadingList(paperIndex, e);
                            }
                        }
                    }
                } catch (e) {
                    console.warn('Add to read list exception:', e);
                }
            }
        } catch (err) {
            console.error('Failed to add to library:', err);
            showMessage('Add failed', 'error');
        }
    })();
}

// Daily arXiv:Remove from to-read list
async function onDailyArxivRemoveFromReadingList(paperIndex, event) {
    if (event) {
        event.stopPropagation();
    }

    // Find the button on the current card and read paper_id
    const card = document.querySelector(`.daily-arxiv-card[data-index="${paperIndex}"]`);
    if (!card) return;

    const btn = card.querySelector('.daily-arxiv-card-action.add-to-reading-list');
    if (!btn) return;

    const paperId = btn.dataset.paperId;
    if (!paperId) return;

    try {
        // Try removing it first to see if you need confirmation
        const res = await fetch(`/api/reading-list/${paperId}/remove`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ delete_files: false })
        });

        if (!res.ok) {
            showMessage('Removal failed', 'error');
            return;
        }

        const data = await res.json();

        if (data.requires_confirmation) {
            // Confirmation of deletion is required and a pop-up window will be displayed.
            const confirmed = confirm(data.message || 'The paper has not been moved to a certain directory. Do you want to delete the paper file?');
            if (confirmed) {
                // User confirms, deletes file
                const deleteResponse = await fetch(`/api/reading-list/${paperId}/remove`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ delete_files: true })
                });
                const deleteData = await deleteResponse.json();
                if (deleteData.success) {
                    await updateReadingListCount();
                    // Purple book button that reverts to "Add to Read List"
                    btn.removeAttribute('data-paper-id');
                    btn.title = 'Add to Readling List';
                    btn.innerHTML = '<i class="fas fa-book-open"></i>';
                    btn.classList.remove('in-list');
                    btn.onclick = (e) => onDailyArxivAddToReadingList(paperIndex, e);
                    showMessage('Removed from to-read list', 'success');
                } else {
                    showMessage('Removal failed', 'error');
                }
            }
        } else if (data.success) {
            // successfully removed
            await updateReadingListCount();
            // Purple book button that reverts to "Add to Read List"
            btn.removeAttribute('data-paper-id');
            btn.title = 'Add to Readling List';
            btn.innerHTML = '<i class="fas fa-book-open"></i>';
            btn.classList.remove('in-list');
            btn.onclick = (e) => onDailyArxivAddToReadingList(paperIndex, e);
            showMessage('Removed from to-read list', 'success');
        } else {
            showMessage('Removal failed', 'error');
        }
    } catch (error) {
        console.error('Removal from to-read list failed:', error);
        showMessage('Removal failed', 'error');
    }
}

// show Daily arXiv Set up modal box
function showDailyArxivSettingsModal() {
    // Switch to the settings interface Daily arXiv panel
    switchTab('setting');
    switchSettingPanel('daily-arxiv');
}

// switch to Daily arXiv view
async function showDailyArxivView() {
    // Hide other views
    document.getElementById('paper-view').style.display = 'none';
    document.getElementById('setting-view').style.display = 'none';
    document.getElementById('daily-arxiv-view').style.display = 'block';

    // hide"to-read list"Label
    const readingListLabel = document.getElementById('reading-list-label');
    if (readingListLabel) {
        readingListLabel.style.display = 'none';
    }

    // Update navigation bar status
    document.querySelectorAll('.nav-tab').forEach(tab => tab.classList.remove('active'));
    const dailyArxivTab = document.querySelector('.nav-tab[data-tab="daily-arxiv"]');
    if (dailyArxivTab) dailyArxivTab.classList.add('active');

    // examine LLM Configure and load settings, dates and papers
    // Check first LLM API state（A pop-up window will be displayed if it fails.）
    await checkDailyArxivLLMConfig();

    await loadDailyArxivSettings();
    // Lazy loading of custom organization list (only loaded when entering Daily arXiv)
    await loadCustomInstitutions();

    // Load available dates first（This will set dailyArxivCurrentDate）
    await loadAvailableDates();

    // Check if the cache has paper data for the current date and partition
    const cacheKey = `${dailyArxivCurrentDate}_${dailyArxivCurrentCategory}`;
    const hasCachedData = dailyArxivPapers[cacheKey] && dailyArxivPapers[cacheKey].length > 0;

    if (!hasCachedData && dailyArxivCategories.length > 0 && dailyArxivCurrentDate) {
        // If there is no data in the cache, try loading it from the server
        await loadPapersForCurrentDate();
    } else if (hasCachedData) {
        // If there is cached data, render directly
        renderDailyArxivGrid();
    }

    // Check whether there is an ongoing crawling task, and if so, automatically start progress polling
    // This ensures that users can see real-time progress when entering the interface
    if (dailyArxivCategories.length > 0) {
        // Check all partitions for ongoing tasks
        await checkAndStartProgressPolling();

        // If a specific partition is currently selected, also checks the progress of that partition
        if (dailyArxivCurrentCategory && dailyArxivCurrentCategory !== 'all') {
            await checkCategoryProgress(dailyArxivCurrentCategory);
        }
    }

    saveCurrentViewState();
}
// ==================== Custom organization configuration management ====================

let customInstitutions = []; // Store custom organization
let hasLoadedCustomInstitutions = false; // Whether the custom mechanism has been loaded
let currentEditingInstitution = null; // Institution currently being edited

/**
 * Load custom organization configuration
 * @param {boolean} force Force reload
 */
async function loadCustomInstitutions(force = false) {
    // Avoid repeated loading (unless forced refresh)
    if (!force && hasLoadedCustomInstitutions && customInstitutions.length > 0) {
        return;
    }

    try {
        const response = await fetch('/api/custom-institutions');
        const data = await response.json();

        if (data.success) {
            customInstitutions = data.institutions || [];
            hasLoadedCustomInstitutions = true;
            renderCustomInstitutions();
        } else {
            console.error('Failed to load custom organization:', data.error);
        }
    } catch (error) {
        console.error('Failed to load custom organization:', error);
    }
}

/**
 * Render a custom institution list（Similar keywords）
 */
function renderCustomInstitutions() {
    const listContainer = document.getElementById('custom-institution-list');

    if (!listContainer) return;

    if (customInstitutions.length === 0) {
        listContainer.innerHTML = `
            <div class="custom-institution-empty">
                There is currently no additional organization configuration, click"Add institution"button to start adding
            </div>
        `;
        return;
    }

    listContainer.innerHTML = customInstitutions.map(inst => `
        <div class="custom-institution-item" ondblclick="editInstitution('${escapeHtml(inst.abbreviation)}')" title="Double click to edit">
            <i class="fas fa-university"></i>
            ${escapeHtml(inst.abbreviation)}
        </div>
    `).join('');
}

/**
 * Display the add organization modal box
 */
function showAddInstitutionModal() {
    currentEditingInstitution = null;
    document.getElementById('institution-modal-title').textContent = 'Add institution mapping';
    document.getElementById('modal-institution-abbr').value = '';
    document.getElementById('modal-institution-abbr').disabled = false;
    document.getElementById('modal-variants-list').innerHTML = '';
    document.getElementById('modal-new-variant').value = '';
    document.getElementById('institution-modal-delete').style.display = 'none';
    updateVariantCount();

    // Show modal box
    const modal = document.getElementById('institution-modal');
    modal.style.display = 'block';
    document.body.style.overflow = 'hidden'; // Prevent background from scrolling

    setTimeout(() => {
        document.getElementById('modal-institution-abbr').focus();
    }, 100);
}

/**
 * Editorial organization（When double clicking on a label）
 */
function editInstitution(abbreviation) {
    const institution = customInstitutions.find(inst => inst.abbreviation === abbreviation);
    if (!institution) return;

    currentEditingInstitution = institution;
    document.getElementById('institution-modal-title').textContent = 'Edit organization mapping';
    document.getElementById('modal-institution-abbr').value = abbreviation;
    document.getElementById('modal-institution-abbr').disabled = true;
    renderModalVariants(institution.variants);
    document.getElementById('modal-new-variant').value = '';
    document.getElementById('institution-modal-delete').style.display = 'inline-flex';
    updateVariantCount();

    // Show modal box
    const modal = document.getElementById('institution-modal');
    modal.style.display = 'block';
    document.body.style.overflow = 'hidden';

    setTimeout(() => {
        document.getElementById('modal-new-variant').focus();
    }, 100);
}

/**
 * Render a list of variants in a modal
 */
function renderModalVariants(variants) {
    const listContainer = document.getElementById('modal-variants-list');

    if (!variants || variants.length === 0) {
        listContainer.innerHTML = '';
        updateVariantCount();
        return;
    }

    listContainer.innerHTML = variants.map(variant => `
        <div class="institution-variant-tag">
            <span class="variant-text">${escapeHtml(variant)}</span>
            <span class="remove-variant" onclick="removeVariantInModal('${escapeHtml(variant)}')">
                <i class="fas fa-times"></i>
            </span>
        </div>
    `).join('');

    updateVariantCount();
}

/**
 * Update variant count display
 */
function updateVariantCount() {
    const variants = getCurrentModalVariants();
    const countEl = document.getElementById('variant-count');
    if (countEl) {
        countEl.textContent = `${variants.length} indivual`;
    }
}

/**
 * Mapping standardized institution names based on custom institutions（Front-end version）
 */
function normalizeAffiliationFrontend(affiliation) {
    if (!affiliation || !customInstitutions) return affiliation;

    const affLower = affiliation.toLowerCase().trim();

    // Traverse all custom institution mappings
    for (const inst of customInstitutions) {
        const abbr = inst.abbreviation;
        const variants = inst.variants || [];

        // Check for an exact match of a variant（Not case sensitive）
        for (const variant of variants) {
            if (variant.toLowerCase().trim() === affLower) {
                console.log(`[Institution] standardization: "${affiliation}" -> "${abbr}"`);
                return abbr;
            }
        }
    }

    return affiliation; // No match, return the original value
}

/**
 * Apply front-end institutional normalization to paper list
 */
function applyFrontendNormalizationToPapers(papers) {
    if (!papers || !Array.isArray(papers)) return papers;

    return papers.map(paper => {
        if (paper.affiliations && Array.isArray(paper.affiliations)) {
            // Standardization organization name
            const normalizedAffiliations = paper.affiliations.map(aff =>
                normalizeAffiliationFrontend(aff)
            );

            // Remove duplicates
            const uniqueAffiliations = [...new Set(normalizedAffiliations)];

            return {
                ...paper,
                affiliations: uniqueAffiliations
            };
        }
        return paper;
    });
}

/**
 * Refresh after institution mapping changes Daily arXiv
 */
async function refreshDailyArxivAfterInstitutionChange() {
    console.log('[Institution] Start refreshing Daily arXiv Paper data...');

    // Check if there is Daily arXiv view
    const dailyArxivSection = document.getElementById('daily-arxiv-section');
    if (!dailyArxivSection) {
        console.log('[Institution] Not here Daily arXiv view, skip refresh');
        return;
    }

    try {
        // Apply normalization to cached papers
        if (typeof dailyArxivPapers !== 'undefined') {
            console.log('[Institution] Apply normalization to cached papers...');
            for (const key in dailyArxivPapers) {
                if (dailyArxivPapers[key] && Array.isArray(dailyArxivPapers[key])) {
                    dailyArxivPapers[key] = applyFrontendNormalizationToPapers(dailyArxivPapers[key]);
                }
            }
        }

        // Re-render the mesh
        if (typeof renderDailyArxivGrid === 'function') {
            renderDailyArxivGrid();
            console.log('[Institution] Thesis grid has been refreshed');
        }

        // Re-render filter（The list of institutions will be updated）
        if (typeof renderDailyArxivFilterAffiliations === 'function') {
            renderDailyArxivFilterAffiliations();
            console.log('[Institution] Institution filter refreshed');
        }

    } catch (error) {
        console.error('[Institution] refresh Daily arXiv fail:', error);
    }
}

/**
 * Add variations in modal
 */
function addVariantInModal() {
    const input = document.getElementById('modal-new-variant');
    const variant = input.value.trim();

    if (!variant) {
        showMessage('Please enter the full name of the organization', 'error');
        return;
    }

    // Get the current variant list
    const currentVariants = getCurrentModalVariants();

    // Check for duplicates
    if (currentVariants.includes(variant)) {
        showMessage('This variant already exists', 'warning');
        return;
    }

    // Add new variant
    currentVariants.push(variant);
    renderModalVariants(currentVariants);

    // Clear input box
    input.value = '';
    input.focus();
    updateVariantCount();
}

/**
 * Remove variations in modal
 */
function removeVariantInModal(variant) {
    const currentVariants = getCurrentModalVariants();
    const newVariants = currentVariants.filter(v => v !== variant);
    renderModalVariants(newVariants);
    updateVariantCount();
}

/**
 * Get the current variant list of the modal box
 */
function getCurrentModalVariants() {
    const listContainer = document.getElementById('modal-variants-list');
    const tags = listContainer.querySelectorAll('.institution-variant-tag');

    return Array.from(tags).map(tag => {
        // pass .variant-text Get text content
        const textSpan = tag.querySelector('.variant-text');
        return textSpan ? textSpan.textContent.trim() : '';
    }).filter(text => text.length > 0);
}

/**
 * depositary institution（modal box）
 */
async function saveInstitutionInModal() {
    console.log('[Institution] Start saving organization...');

    const abbreviation = document.getElementById('modal-institution-abbr').value.trim();
    const variants = getCurrentModalVariants();

    console.log('[Institution] abbreviation:', abbreviation);
    console.log('[Institution] Variants:', variants);

    if (!abbreviation) {
        showMessage('Please enter a standard abbreviation', 'error');
        return;
    }

    if (variants.length === 0) {
        showMessage('At least one full name variant needs to be added', 'error');
        return;
    }

    try {
        console.log('[Institution] Send request to /api/custom-institutions');
        const response = await fetch('/api/custom-institutions', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                abbreviation: abbreviation,
                variants: variants
            })
        });

        console.log('[Institution] response received:', response.status);
        const data = await response.json();
        console.log('[Institution] response data:', data);

        if (data.success) {
            showMessage('The institution has been saved and the paper is being refreshed....', 'success');
            closeInstitutionModal();
            await loadCustomInstitutions(true);

            // refresh Daily arXiv of thesis data to enable the new institutional mapping
            await refreshDailyArxivAfterInstitutionChange();
        } else {
            showMessage('Save failed: ' + data.error, 'error');
        }
    } catch (error) {
        console.error('[Institution] Failed to save organization:', error);
        showMessage('Save failed: ' + error.message, 'error');
    }
}

/**
 * Delete organization（modal box）
 */
async function deleteInstitutionInModal() {
    if (!currentEditingInstitution) return;

    const abbreviation = currentEditingInstitution.abbreviation;

    if (!confirm(`Are you sure you want to delete the organization? ${abbreviation} ?`)) {
        return;
    }

    try {
        const response = await fetch(`/api/custom-institutions/${encodeURIComponent(abbreviation)}`, {
            method: 'DELETE'
        });

        const data = await response.json();

        if (data.success) {
            showMessage('Deleted, refreshing the paper...', 'success');
            closeInstitutionModal();
            await loadCustomInstitutions(true);

            // refresh Daily arXiv paper data
            await refreshDailyArxivAfterInstitutionChange();
        } else {
            showMessage('Delete failed: ' + data.error, 'error');
        }
    } catch (error) {
        console.error('Failed to delete organization:', error);
        showMessage('Delete failed', 'error');
    }
}

/**
 * Close the organization editing modal box
 */
function closeInstitutionModal() {
    document.getElementById('institution-modal').style.display = 'none';
    document.body.style.overflow = ''; // Restore background scrolling
    currentEditingInstitution = null;
}

/**
 * Initialize custom organization management
 */
function initCustomInstitutionManagement() {
    // Modal box enter key support
    const variantInput = document.getElementById('modal-new-variant');
    if (variantInput) {
        variantInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                addVariantInModal();
            }
        });
    }

    // ESC key to close the modal
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const modal = document.getElementById('institution-modal');
            if (modal && modal.style.display === 'flex') {
                closeInstitutionModal();
            }
        }
    });
}

// After switching to Daily arXiv Load custom institutions when setting up the panel
onAppReady(() => {
    // Initialize custom organization management
    initCustomInstitutionManagement();

    // Monitoring settings panel switch（Make sure to switch to Daily arXiv Also refresh when setting）
    const dailyArxivSettingBtn = document.querySelector('.setting-nav-item[data-setting="daily-arxiv"]');
    if (dailyArxivSettingBtn) {
        dailyArxivSettingBtn.addEventListener('click', () => {
            // Lazy loading to ensure the panel is displayed
            setTimeout(() => {
                loadCustomInstitutions();
            }, 100);
        });
    }
});

// ==================== Export Function ====================
let exportTaskId = null;
let exportProgressInterval = null;

// Load papers directory path
async function loadPapersDir() {
    if (hasLoadedPapersDir) return;

    try {
        const pathElement = document.getElementById('papers-dir-path');
        if (pathElement) {
            const response = await fetch('/api/papers-dir');
            const data = await response.json();
            if (data.success) {
                pathElement.textContent = data.path;
                hasLoadedPapersDir = true;
            }
        }
    } catch (error) {
        console.error('get papers Directory path failed:', error);
    }
}

// Initialize export function
async function initExportFeature() {
    const btnStartExport = document.getElementById('btn-start-export');
    const btnCancelExport = document.getElementById('btn-cancel-export');
    const btnDownloadExport = document.getElementById('btn-download-export');

    if (btnStartExport) {
        btnStartExport.addEventListener('click', startExport);
    }

    if (btnCancelExport) {
        btnCancelExport.addEventListener('click', cancelExport);
    }

    if (btnDownloadExport) {
        btnDownloadExport.addEventListener('click', downloadExport);
    }
}

// Start export
async function startExport() {
    const btnStart = document.getElementById('btn-start-export');
    const progressContainer = document.getElementById('export-progress-container');

    // Disable start button
    btnStart.disabled = true;
    btnStart.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Starting...';

    try {
        const response = await fetch('/api/export/start', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({})
        });

        const data = await response.json();

        if (!data.success) {
            showMessage(data.error || 'Failed to start export', 'error');
            btnStart.disabled = false;
            btnStart.innerHTML = '<i class="fas fa-download"></i> Start export';
            return;
        }

        exportTaskId = data.task_id;

        // Show progress container
        progressContainer.style.display = 'block';
        btnStart.style.display = 'none';

        // Start polling progress
        startExportProgressPolling();

        showMessage('Export task started', 'success');

    } catch (error) {
        console.error('Failed to start export:', error);
        showMessage('Failed to start export: ' + error.message, 'error');
        btnStart.disabled = false;
        btnStart.innerHTML = '<i class="fas fa-download"></i> Start export';
    }
}

// Polling for export progress
function startExportProgressPolling() {
    if (exportProgressInterval) {
        clearInterval(exportProgressInterval);
    }

    // Query once now
    checkExportProgress();

    // Query once per second
    exportProgressInterval = setInterval(checkExportProgress, 1000);
}

// Check export progress
async function checkExportProgress() {
    if (!exportTaskId) return;

    try {
        const response = await fetch(`/api/export/status/${exportTaskId}`);
        const data = await response.json();

        if (!data.success) {
            stopExportProgressPolling();
            return;
        }

        const task = data.task;
        updateExportProgress(task);

        // Stop polling if task completes or fails
        if (task.status === 'completed' || task.status === 'failed' || task.status === 'cancelled') {
            stopExportProgressPolling();
        }

    } catch (error) {
        console.error('Failed to query export progress:', error);
    }
}

// Stop polling
function stopExportProgressPolling() {
    if (exportProgressInterval) {
        clearInterval(exportProgressInterval);
        exportProgressInterval = null;
    }
}

// Update export progress display
function updateExportProgress(task) {
    const statusText = document.getElementById('export-status-text');
    const progressText = document.getElementById('export-progress-text');
    const progressFill = document.getElementById('export-progress-fill');
    const currentPaper = document.getElementById('export-current-paper');
    const btnDownload = document.getElementById('btn-download-export');
    const btnCancel = document.getElementById('btn-cancel-export');

    // Update status text
    if (task.status === 'pending') {
        statusText.textContent = 'In preparation...';
    } else if (task.status === 'running') {
        statusText.textContent = 'Exporting...';
    } else if (task.status === 'completed') {
        statusText.textContent = 'Export completed!';
        btnDownload.style.display = 'inline-flex';
        btnCancel.style.display = 'none';
    } else if (task.status === 'failed') {
        statusText.textContent = 'Export failed';
        statusText.style.color = '#d73a49';
        currentPaper.textContent = task.error || 'unknown error';
        currentPaper.style.color = '#d73a49';
        btnCancel.style.display = 'none';
    } else if (task.status === 'cancelled') {
        statusText.textContent = 'Canceled';
        statusText.style.color = '#6a737d';
        btnCancel.style.display = 'none';
    }

    // update progress
    if (task.total > 0) {
        const percent = Math.round((task.progress / task.total) * 100);
        progressText.textContent = `${task.progress} / ${task.total}`;
        progressFill.style.width = percent + '%';
    } else {
        progressText.textContent = '0 / 0';
        progressFill.style.width = '0%';
    }

    // Update current paper
    if (task.current_paper && task.status === 'running') {
        currentPaper.textContent = task.current_paper;
        currentPaper.style.color = '#57606a';
    }
}

// Cancel export
async function cancelExport() {
    if (!exportTaskId) return;

    if (!confirm('Are you sure you want to cancel the export?')) {
        return;
    }

    try {
        const response = await fetch(`/api/export/cancel/${exportTaskId}`, {
            method: 'POST'
        });

        const data = await response.json();

        if (data.success) {
            showMessage('Export canceled', 'info');
            resetExportUI();
        } else {
            showMessage(data.error || 'Cancellation failed', 'error');
        }

    } catch (error) {
        console.error('Cancel export failed:', error);
        showMessage('Cancel export failed: ' + error.message, 'error');
    }
}

// Download export file
async function downloadExport() {
    if (!exportTaskId) return;

    try {
        // Download directly from your browser
        window.location.href = `/api/export/download/${exportTaskId}`;

        showMessage('Export file download has started', 'success');

        // Reset after downloading UI
        setTimeout(() => {
            resetExportUI();
        }, 2000);

    } catch (error) {
        console.error('Failed to download export file:', error);
        showMessage('Download failed: ' + error.message, 'error');
    }
}

// Reset export UI
function resetExportUI() {
    const btnStart = document.getElementById('btn-start-export');
    const progressContainer = document.getElementById('export-progress-container');
    const btnDownload = document.getElementById('btn-download-export');
    const btnCancel = document.getElementById('btn-cancel-export');
    const statusText = document.getElementById('export-status-text');
    const currentPaper = document.getElementById('export-current-paper');

    btnStart.disabled = false;
    btnStart.innerHTML = '<i class="fas fa-download"></i> Start export';
    btnStart.style.display = 'inline-flex';

    progressContainer.style.display = 'none';
    btnDownload.style.display = 'none';
    btnCancel.style.display = 'inline-flex';

    statusText.textContent = 'Exporting...';
    statusText.style.color = '';
    currentPaper.textContent = '';
    currentPaper.style.color = '';

    exportTaskId = null;
    stopExportProgressPolling();
}

// Initialized when page loads
onAppReady(() => {
    initExportFeature();
});

// ========== Newbie guide function ==========
async function showOnboardingModal() {
    const modal = document.getElementById('onboarding-modal');
    if (modal) {
        // Load current AI language setting and set it in the onboarding modal
        try {
            const userSettings = await getUserSettings();
            const aiLanguage = userSettings.aiLanguage || 'zh';
            const onboardingLanguageEl = document.getElementById('onboarding-ai-language');
            if (onboardingLanguageEl) {
                onboardingLanguageEl.value = aiLanguage;
            }
        } catch (e) {
            console.error('[Onboarding] Failed to load AI language setting:', e);
        }

        modal.style.display = 'flex';
        // Prevent background from scrolling
        document.body.style.overflow = 'hidden';
        console.log('[Onboarding] Newbie guide pop-up window has been displayed');
    } else {
        console.error('[Onboarding] Newbie guide modal box element not found');
    }
}

async function closeOnboardingModal() {
    const modal = document.getElementById('onboarding-modal');
    const checkbox = document.getElementById('onboarding-dont-show');
    const languageEl = document.getElementById('onboarding-ai-language');

    if (modal) {
        modal.style.display = 'none';
        // Restore background scrolling
        document.body.style.overflow = '';
    }

    // Save AI language setting if changed
    if (languageEl) {
        try {
            const selectedLanguage = languageEl.value;
            await saveUserSettings({ aiLanguage: selectedLanguage });
            console.log('[Onboarding] AI language saved:', selectedLanguage);

            // Update Agentic settings panel if it's open
            const aiLanguageEl = document.getElementById('ai-language');
            if (aiLanguageEl) {
                aiLanguageEl.value = selectedLanguage;
            }
        } catch (e) {
            console.error('[Onboarding] Failed to save AI language setting:', e);
        }
    }

    // If the user checked"Don't remind me next time", save to user settings
    if (checkbox && checkbox.checked) {
        try {
            await saveUserSettings({ onboardingDontShow: true });
            console.log('[Onboarding] User chose not to show again, settings saved');
        } catch (e) {
            console.error('[Onboarding] Failed to save newbie guide settings:', e);
        }
    } else {
        // The user has not checked, make sure it is set to false, it will be displayed next time
        try {
            await saveUserSettings({ onboardingDontShow: false });
            console.log('[Onboarding] User did not check "Don\'t remind me again", it will still be displayed next time');
        } catch (e) {
            console.error('[Onboarding] Failed to save newbie guide settings:', e);
        }
    }
}

async function checkAndShowOnboarding() {
    try {
        // Check if it has been set from user settings"Don’t remind me next time"
        const userSettings = await getUserSettings();
        const dontShow = userSettings.onboardingDontShow;

        // If the user has chosen not to show it again, skip the pop-up window
        if (dontShow === true) {
            console.log('[Onboarding] The user has chosen not to show it again and skip the pop-up window.');
            return;
        }

        // Show newbie guide
        // Delay the display a bit to ensure the page is fully loaded
        console.log('[Onboarding] Show newbie guide popup（onboardingDontShow:', dontShow, '）');
        setTimeout(() => {
            showOnboardingModal();
        }, 500);
    } catch (e) {
        console.error('[Onboarding] Checking the newbie guide settings failed:', e);
    }
}

// Check whether you need to display the newbie guide after the page is loaded.
// Use immediate execution functions to support lazy loading
(function () {
    async function initOnboarding() {
        await checkAndShowOnboarding();
    }

    // if DOM Loading is complete, execute immediately
    onAppReady(initOnboarding);
})();

// Sidebar Toggle Logic
(function () {
    function initSidebarToggle() {
        const leftSidebar = document.querySelector('.sidebar');
        const rightSidebar = document.querySelector('.info-panel');
        const leftToggleBtn = document.getElementById('toggle-left-sidebar');
        const rightToggleBtn = document.getElementById('toggle-right-sidebar');

        // Toggle Left Sidebar
        if (leftToggleBtn && leftSidebar) {
            leftToggleBtn.addEventListener('click', () => {
                const isVisible = leftSidebar.style.display !== 'none';
                leftSidebar.style.display = isVisible ? 'none' : 'flex';
                leftToggleBtn.classList.toggle('active', !isVisible);
                window.dispatchEvent(new Event('resize'));

                // If expanded and not loaded, load category
                if (!isVisible && !hasLoadedCategories) {
                    loadCategories();
                }
            });
        }

        // Toggle Right Sidebar
        if (rightToggleBtn && rightSidebar) {
            rightToggleBtn.addEventListener('click', () => {
                const isVisible = rightSidebar.style.display !== 'none';
                rightSidebar.style.display = isVisible ? 'none' : 'flex';
                rightToggleBtn.classList.toggle('active', !isVisible);
                window.dispatchEvent(new Event('resize'));
            });
        }
    }

    onAppReady(initSidebarToggle);
})();

// Chat Interaction Logic
let currentChatPaperId = null;
let chatHistory = [];
const CHAT_COMMON_PROMPTS_STORAGE_KEY = 'chatCommonPrompts';
const DEFAULT_CHAT_COMMON_PROMPTS = [
    '总结一下论文的主要内容',
    '请用一句话概括整个工作？',
    '这篇论文试图解决什么痛点问题？',
    '这个痛点在真实应用场景中有多严重？ 是否有具体案例支撑？',
    '论文如何解决这个问题？',
    '这篇论文的主要贡献/创新点是什么？',
    '这篇论文有哪些相关研究？',
    '论文的实验设置（数据集、指标、对比方法）分别是什么？',
    '论文做了哪些实验？',
    '有什么可以进一步探索的点？',
    '有没有开源代码？GitHub链接在哪里？'
];

function loadChatCustomPrompts() {
    try {
        const raw = localStorage.getItem(CHAT_COMMON_PROMPTS_STORAGE_KEY);
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) return parsed.filter(x => typeof x === 'string');
        if (parsed && Array.isArray(parsed.prompts)) return parsed.prompts.filter(x => typeof x === 'string');
        return [];
    } catch (e) {
        return [];
    }
}

function saveChatCustomPrompts(prompts) {
    const cleaned = Array.from(new Set((prompts || [])
        .filter(x => typeof x === 'string')
        .map(x => x.trim())
        .filter(Boolean))).slice(0, 200);
    try {
        localStorage.setItem(CHAT_COMMON_PROMPTS_STORAGE_KEY, JSON.stringify({ prompts: cleaned }));
    } catch (e) { }
    return cleaned;
}

function getAllChatPromptsWithSource() {
    const builtIn = (DEFAULT_CHAT_COMMON_PROMPTS || []).map(text => ({ text, source: '内置' }));
    const custom = loadChatCustomPrompts().map(text => ({ text, source: '自定义' }));
    const seen = new Set();
    const merged = [];
    [...custom, ...builtIn].forEach(item => {
        const key = (item.text || '').trim();
        if (!key) return;
        if (seen.has(key)) return;
        seen.add(key);
        merged.push(item);
    });
    return merged;
}

function setChatInputValue(value, { focus = true } = {}) {
    const textarea = document.getElementById('chat-input');
    if (!textarea) return;
    textarea.value = value || '';
    textarea.style.height = 'auto';
    textarea.style.height = (textarea.scrollHeight) + 'px';
    if (focus) {
        textarea.focus();
        const pos = textarea.value.length;
        textarea.setSelectionRange(pos, pos);
    }
}

function showChatCommonPromptsManager() {
    const modalEl = document.getElementById('modal');
    if (!modalEl) return;
    const prevZ = modalEl.style.zIndex;
    modalEl.style.zIndex = '1100';
    let closeManager = () => {
        modalEl.style.zIndex = prevZ;
        hideModal();
    };

    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');
    let confirmBtn = document.getElementById('modal-confirm');
    let cancelBtn = document.getElementById('modal-cancel');
    if (!modalTitle || !modalBody || !confirmBtn || !cancelBtn) return;

    modalTitle.textContent = '常用问题';
    modalBody.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:14px;">
            <div style="color:#6b7280; font-size:12px; line-height:1.5;">
                在输入框里输入 <b>/</b> 可唤醒常用问题下拉框；也可以在这里维护你的自定义问题。
            </div>
            <div>
                <div style="font-weight:600; margin-bottom:8px;">内置问题</div>
                <div id="chat-built-in-prompts" style="display:flex; flex-wrap:wrap; gap:8px;"></div>
            </div>
            <div>
                <div style="font-weight:600; margin-bottom:8px;">自定义问题</div>
                <div style="display:flex; gap:8px; margin-bottom:10px;">
                    <input id="chat-custom-prompt-input" type="text" placeholder="输入一条常用问题…" style="flex:1; padding:8px 10px; border:1px solid #d1d5db; border-radius:8px; font-size:14px;">
                    <button id="chat-custom-prompt-add-btn" class="btn btn-primary" type="button" style="padding:8px 12px; border-radius:8px;">添加</button>
                </div>
                <div id="chat-custom-prompt-list" style="display:flex; flex-direction:column; gap:8px;"></div>
            </div>
        </div>
    `;

    const builtInContainer = document.getElementById('chat-built-in-prompts');
    if (builtInContainer) {
        builtInContainer.style.cssText = 'display:flex; flex-direction:column; gap:8px;';
        DEFAULT_CHAT_COMMON_PROMPTS.forEach(text => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-secondary';
            btn.style.cssText = 'padding:10px 12px; border-radius:10px; font-size:13px; border:1px solid #e5e7eb; background:#f9fafb; color:#111827; cursor:pointer; width:100%; text-align:left; white-space:normal; line-height:1.45; display:flex; justify-content:flex-start;';
            btn.textContent = text;
            btn.addEventListener('click', () => {
                setChatInputValue(text, { focus: true });
                closeManager();
            });
            builtInContainer.appendChild(btn);
        });
    }

    let customPrompts = loadChatCustomPrompts();

    function renderCustomPrompts() {
        const listEl = document.getElementById('chat-custom-prompt-list');
        if (!listEl) return;
        listEl.innerHTML = '';
        if (!customPrompts.length) {
            const empty = document.createElement('div');
            empty.style.cssText = 'color:#6b7280; font-size:13px;';
            empty.textContent = '暂无自定义问题。';
            listEl.appendChild(empty);
            return;
        }
        customPrompts.forEach((text, index) => {
            const row = document.createElement('div');
            row.style.cssText = 'display:flex; gap:8px; align-items:center;';
            const input = document.createElement('input');
            input.type = 'text';
            input.value = text;
            input.style.cssText = 'flex:1; padding:8px 10px; border:1px solid #d1d5db; border-radius:8px; font-size:14px;';
            input.addEventListener('input', () => {
                customPrompts[index] = input.value;
            });
            const useBtn = document.createElement('button');
            useBtn.type = 'button';
            useBtn.className = 'btn btn-secondary';
            useBtn.style.cssText = 'padding:8px 10px; border-radius:8px;';
            useBtn.textContent = '填充';
            useBtn.addEventListener('click', () => {
                const v = (customPrompts[index] || '').trim();
                if (!v) return;
                setChatInputValue(v, { focus: true });
                closeManager();
            });
            const delBtn = document.createElement('button');
            delBtn.type = 'button';
            delBtn.className = 'btn btn-secondary';
            delBtn.style.cssText = 'padding:8px 10px; border-radius:8px; color:#dc2626; border-color:#fee2e2; background:#fff;';
            delBtn.textContent = '删除';
            delBtn.addEventListener('click', () => {
                customPrompts.splice(index, 1);
                renderCustomPrompts();
            });
            row.appendChild(input);
            row.appendChild(useBtn);
            row.appendChild(delBtn);
            listEl.appendChild(row);
        });
    }

    renderCustomPrompts();

    const addBtn = document.getElementById('chat-custom-prompt-add-btn');
    const addInput = document.getElementById('chat-custom-prompt-input');
    if (addBtn && addInput) {
        const add = () => {
            const value = (addInput.value || '').trim();
            if (!value) return;
            customPrompts.unshift(value);
            addInput.value = '';
            renderCustomPrompts();
        };
        addBtn.addEventListener('click', add);
        addInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
                e.preventDefault();
                add();
            }
        });
    }

    const confirmClone = confirmBtn.cloneNode(true);
    const cancelClone = cancelBtn.cloneNode(true);
    confirmBtn.parentNode.replaceChild(confirmClone, confirmBtn);
    cancelBtn.parentNode.replaceChild(cancelClone, cancelBtn);
    confirmBtn = document.getElementById('modal-confirm');
    cancelBtn = document.getElementById('modal-cancel');

    confirmBtn.style.display = 'inline-block';
    confirmBtn.textContent = '保存并关闭';
    cancelBtn.textContent = '取消';

    const restoreZ = () => {
        modalEl.style.zIndex = prevZ;
        modalEl.removeEventListener('click', outsideClickRestore, true);
        closeBtn?.removeEventListener('click', closeRestore);
        cancelBtn?.removeEventListener('click', cancelRestore);
    };

    const outsideClickRestore = (e) => {
        if (e.target === modalEl) restoreZ();
    };
    const closeBtn = modalEl.querySelector('.close');
    const closeRestore = () => restoreZ();
    const cancelRestore = () => restoreZ();

    modalEl.addEventListener('click', outsideClickRestore, true);
    closeBtn?.addEventListener('click', closeRestore);
    cancelBtn?.addEventListener('click', cancelRestore);
    closeManager = () => {
        restoreZ();
        hideModal();
    };

    confirmBtn.onclick = () => {
        customPrompts = saveChatCustomPrompts(customPrompts);
        restoreZ();
        hideModal();
    };
    cancelBtn.onclick = () => {
        restoreZ();
        hideModal();
    };

    showModal();
    setTimeout(() => addInput?.focus(), 50);
}

let chatPromptDropdownState = {
    open: false,
    items: [],
    activeIndex: 0,
    startIndex: -1,
    query: ''
};

function getChatSlashContext(text, cursorPos) {
    if (cursorPos == null) cursorPos = text.length;
    const upto = text.slice(0, cursorPos);
    for (let i = upto.length - 1; i >= 0; i--) {
        if (upto[i] !== '/') continue;
        const prev = i === 0 ? '' : upto[i - 1];
        if (i !== 0 && prev && !/\s/.test(prev)) continue;
        const query = upto.slice(i + 1);
        return { startIndex: i, query };
    }
    return { startIndex: -1, query: '' };
}

function filterChatPrompts(items, query) {
    const q = (query || '').trim().toLowerCase();
    if (!q) return items.slice(0, 12);
    const ranked = items
        .map(item => {
            const t = (item.text || '').toLowerCase();
            const idx = t.indexOf(q);
            return { item, idx };
        })
        .filter(x => x.idx >= 0)
        .sort((a, b) => a.idx - b.idx)
        .map(x => x.item);
    return ranked.slice(0, 12);
}

function renderChatPromptDropdown() {
    const dropdown = document.getElementById('chat-prompt-dropdown');
    if (!dropdown) return;
    if (!chatPromptDropdownState.open) {
        dropdown.classList.remove('show');
        dropdown.innerHTML = '';
        return;
    }
    const items = chatPromptDropdownState.items || [];
    if (!items.length) {
        dropdown.innerHTML = `<div class="chat-prompt-empty">没有匹配的常用问题</div>`;
        dropdown.classList.add('show');
        return;
    }
    dropdown.innerHTML = items.map((it, idx) => {
        const active = idx === chatPromptDropdownState.activeIndex ? 'active' : '';
        return `
            <div class="chat-prompt-item ${active}" data-index="${idx}">
                <div class="chat-prompt-text">${escapeHtml(it.text)}</div>
                <div class="chat-prompt-badge">${escapeHtml(it.source || '')}</div>
            </div>
        `;
    }).join('');
    dropdown.classList.add('show');
}

function closeChatPromptDropdown() {
    chatPromptDropdownState.open = false;
    chatPromptDropdownState.items = [];
    chatPromptDropdownState.activeIndex = 0;
    chatPromptDropdownState.startIndex = -1;
    chatPromptDropdownState.query = '';
    renderChatPromptDropdown();
}

function openChatPromptDropdown({ startIndex, query }) {
    const textarea = document.getElementById('chat-input');
    if (!textarea) return;
    const all = getAllChatPromptsWithSource();
    const filtered = filterChatPrompts(all, query);
    chatPromptDropdownState.open = true;
    chatPromptDropdownState.items = filtered;
    chatPromptDropdownState.activeIndex = 0;
    chatPromptDropdownState.startIndex = startIndex;
    chatPromptDropdownState.query = query || '';
    renderChatPromptDropdown();
}

function selectChatPromptByIndex(index) {
    const textarea = document.getElementById('chat-input');
    if (!textarea) return;
    const item = (chatPromptDropdownState.items || [])[index];
    if (!item) return;
    const cursorPos = textarea.selectionStart ?? textarea.value.length;
    const startIndex = chatPromptDropdownState.startIndex;
    if (startIndex < 0 || startIndex > cursorPos) return;
    const before = textarea.value.slice(0, startIndex);
    const after = textarea.value.slice(cursorPos);
    const inserted = item.text;
    textarea.value = before + inserted + after;
    const newPos = (before + inserted).length;
    textarea.setSelectionRange(newPos, newPos);
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
    closeChatPromptDropdown();
    textarea.focus();
}

// Configure Marked.js with custom renderer
function configureMarked() {
    if (typeof marked === 'undefined') return;

    // Prevent double configuration
    if (marked.defaults && marked.defaults.renderer && marked.defaults.renderer._customized) return;

    const renderer = new marked.Renderer();
    renderer._customized = true; // Flag to prevent re-init

    renderer.code = function (code, language) {
        const validLang = !!(language && hljs.getLanguage(language));
        const highlighted = validLang ? hljs.highlight(code, { language }).value : hljs.highlightAuto(code).value;
        const langLabel = language || 'text';

        return `
        <div class="code-block-wrapper">
            <div class="code-header">
                <span class="code-lang">${langLabel}</span>
                <button class="copy-btn" onclick="window.copyChatCode(this)">
                    <i class="fas fa-copy"></i> Copy
                </button>
            </div>
            <pre><code class="hljs ${language}">${highlighted}</code><textarea style="display:none">${code}</textarea></pre>
        </div>`;
    };

    marked.setOptions({
        renderer: renderer,
        breaks: true,
        gfm: true
    });
}

// Global copy function for chat code blocks
window.copyChatCode = function (btn) {
    const wrapper = btn.closest('.code-block-wrapper');
    const textarea = wrapper.querySelector('textarea');

    if (navigator.clipboard && textarea) {
        navigator.clipboard.writeText(textarea.value).then(() => {
            const originalHtml = btn.innerHTML;
            btn.innerHTML = '<i class="fas fa-check"></i> Copied!';
            setTimeout(() => {
                btn.innerHTML = originalHtml;
            }, 2000);
        });
    }
};

async function openChat(paperId, event) {
    if (event) event.stopPropagation();
    currentChatPaperId = paperId;
    currentSessionId = null;
    chatHistory = [];
    closeChatPromptDropdown();

    configureMarked();

    const paper = papers.find(p => p.id === paperId);
    if (!paper) return;

    // Update modal title
    const modalTitle = document.getElementById('chat-modal-title');
    if (modalTitle) {
        modalTitle.innerHTML = `<i class="fas fa-comments"></i> Chat with: ${paper.title || paper.filename}`;
    }

    // Show modal first
    const modal = document.getElementById('chat-modal');
    if (modal) {
        modal.classList.add('show');
    }

    // Clear main chat area
    const chatBody = document.getElementById('chat-messages');
    if (chatBody) {
        chatBody.innerHTML = '';
    }

    const inputEl = document.getElementById('chat-input');
    if (inputEl) {
        inputEl.value = '';
        inputEl.style.height = 'auto';
    }

    const sessionListEl = document.getElementById('chat-session-list');
    if (sessionListEl) {
        sessionListEl.innerHTML = '<div style="text-align:center; padding:16px; color:#999;"><i class="fas fa-spinner fa-spin"></i> Loading...</div>';
    }

    // Load sessions
    await loadChatSessions(paperId);
}

async function loadChatSessions(paperId) {
    const expectedPaperId = paperId;
    const sessionListEl = document.getElementById('chat-session-list');
    if (!sessionListEl) return;
    sessionListEl.innerHTML = '<div style="text-align:center; padding:16px; color:#999;"><i class="fas fa-spinner fa-spin"></i> Loading...</div>';
    try {
        const response = await fetch(`/api/paper/chat/sessions?paper_id=${paperId}`);
        const data = await response.json();
        if (currentChatPaperId !== expectedPaperId) return;
        sessionListEl.innerHTML = '';

        if (data.success && data.sessions.length > 0) {
            // Render list
            data.sessions.forEach(session => {
                const el = createSessionElement(session);
                sessionListEl.appendChild(el);
            });

            // Auto-select first session
            await switchSession(data.sessions[0].id);
        } else {
            // No sessions, create a new one automatically
            await createNewSession(true);
        }

    } catch (e) {
        console.error("Failed to load sessions:", e);
        if (currentChatPaperId !== expectedPaperId) return;
        sessionListEl.innerHTML = '';
        await createNewSession(true);
    }
}

function createSessionElement(session) {
    const div = document.createElement('div');
    div.className = 'chat-session-item';
    div.dataset.id = session.id;

    // Format date
    const date = new Date(session.updated_at * 1000);
    const dateStr = date.toLocaleDateString() + ' ' + date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    div.innerHTML = `
        <span class="session-title">${session.title}</span>
        <span class="session-preview">${session.preview || 'No messages'}</span>
        <div class="session-date">${dateStr}</div>
        <button class="session-delete-btn" onclick="deleteSession('${session.id}', event)" title="Delete Chat">
            <i class="fas fa-trash"></i>
        </button>
    `;

    div.onclick = () => switchSession(session.id);
    return div;
}

async function createNewSession(isAuto = false) {
    if (!currentChatPaperId) return;

    // Optimistic UI update
    const sessionListEl = document.getElementById('chat-session-list');

    try {
        const response = await fetch('/api/paper/chat/session', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paper_id: currentChatPaperId })
        });
        const data = await response.json();

        if (data.success) {
            const session = data.session;
            session.preview = 'New conversation';
            const el = createSessionElement(session);

            if (sessionListEl.firstChild) {
                sessionListEl.insertBefore(el, sessionListEl.firstChild);
            } else {
                sessionListEl.appendChild(el);
            }

            await switchSession(session.id);

            // Focus input
            setTimeout(() => {
                document.getElementById('chat-input')?.focus();
            }, 100);
        }
    } catch (e) {
        console.error("Failed to create session:", e);
    }
}

async function switchSession(sessionId) {
    if (currentSessionId === sessionId) return;
    currentSessionId = sessionId;

    // Update active state in sidebar
    document.querySelectorAll('.chat-session-item').forEach(el => {
        el.classList.toggle('active', el.dataset.id === sessionId);
    });

    // Load session details
    const chatBody = document.getElementById('chat-messages');
    chatBody.innerHTML = '<div style="text-align:center; padding:20px; color:#999;"><i class="fas fa-spinner fa-spin"></i> Loading...</div>';

    try {
        const response = await fetch(`/api/paper/chat/session?paper_id=${currentChatPaperId}&session_id=${sessionId}`);
        const data = await response.json();

        chatBody.innerHTML = '';
        chatHistory = [];

        if (data.success && data.session) {
            const messages = data.session.messages || [];

            // Always show greeting for empty sessions
            if (messages.length === 0) {
                appendChatMessage('ai', 'Hello! I have read this paper. You can ask me anything about it.');
            } else {
                messages.forEach(msg => {
                    // Map 'assistant' back to 'ai' for UI function if needed, but standard is 'assistant'
                    const role = msg.role === 'assistant' ? 'ai' : msg.role;
                    appendChatMessage(role, msg.content);
                    chatHistory.push({ role: msg.role, content: msg.content });
                });
            }

            // Scroll to bottom
            setTimeout(() => {
                chatBody.scrollTop = chatBody.scrollHeight;
            }, 50);
        } else {
            await createNewSession(true);
        }
    } catch (e) {
        chatBody.innerHTML = '<div style="text-align:center; color:red;">Failed to load chat history.</div>';
        console.error(e);
    }
}

async function deleteSession(sessionId, event) {
    if (event) event.stopPropagation();
    if (!confirm('Are you sure you want to delete this chat?')) return;

    try {
        const response = await fetch(`/api/paper/chat/session?paper_id=${currentChatPaperId}&session_id=${sessionId}`, {
            method: 'DELETE'
        });
        const data = await response.json();

        if (data.success) {
            // Remove from UI
            const el = document.querySelector(`.chat-session-item[data-id="${sessionId}"]`);
            if (el) el.remove();

            // If current session was deleted, switch to another or create new
            if (currentSessionId === sessionId) {
                const firstSession = document.querySelector('.chat-session-item');
                if (firstSession) {
                    switchSession(firstSession.dataset.id);
                } else {
                    createNewSession(true);
                }
            }
        }
    } catch (e) {
        console.error("Failed to delete session:", e);
    }
}

function closeChatModal() {
    const modal = document.getElementById('chat-modal');
    if (modal) {
        modal.classList.remove('show');
    }
    closeChatPromptDropdown();
    currentChatPaperId = null;
    currentSessionId = null;
    chatHistory = [];

    const chatBody = document.getElementById('chat-messages');
    if (chatBody) {
        chatBody.innerHTML = '';
    }

    const sessionListEl = document.getElementById('chat-session-list');
    if (sessionListEl) {
        sessionListEl.innerHTML = '';
    }
}

async function sendChatMessage() {
    if (!currentChatPaperId || !currentSessionId) return;

    const textarea = document.getElementById('chat-input');
    if (!textarea) return;
    closeChatPromptDropdown();
    const message = textarea.value.trim();
    if (!message) return;

    // Clear input
    textarea.value = '';
    textarea.style.height = 'auto';

    // Append user message
    appendChatMessage('user', message);
    chatHistory.push({ role: 'user', content: message });

    // Create placeholder for AI response with thinking indicator
    const aiMessageRow = appendChatMessage('ai', '', true);
    const aiBubble = aiMessageRow.querySelector('.message-bubble');

    aiBubble.innerHTML = `
        <div class="typing-indicator">
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        </div>`;

    let fullResponse = '';

    try {
        const response = await fetch('/api/paper/chat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                paper_id: currentChatPaperId,
                messages: chatHistory,
                session_id: currentSessionId
            })
        });

        if (!response.ok) {
            let serverMessage = `Request failed (${response.status})`;
            try {
                const contentType = response.headers.get('content-type') || '';
                if (contentType.includes('application/json')) {
                    const errData = await response.json();
                    if (errData && errData.error) {
                        serverMessage = errData.error;
                    } else if (errData && errData.message) {
                        serverMessage = errData.message;
                    }
                } else {
                    const errText = await response.text();
                    if (errText) serverMessage = errText;
                }
            } catch (e) {
                // ignore parse errors
            }
            throw new Error(serverMessage);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        let isFirstChunk = true;

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });

            let contentToDisplay = chunk;

            if (isFirstChunk) {
                const lines = chunk.split('\n');
                // Check if first line is JSON
                try {
                    const meta = JSON.parse(lines[0]);
                    if (meta.session_id) {
                        if (currentSessionId !== meta.session_id) {
                            currentSessionId = meta.session_id;
                        }
                        // Remove first line from content
                        contentToDisplay = lines.slice(1).join('\n');
                    }
                } catch (e) {
                    // Not JSON, treat as content
                }
                isFirstChunk = false;
            }

            if (!contentToDisplay) continue;

            fullResponse += contentToDisplay;

            if (typeof marked !== 'undefined') {
                // Add blinking cursor
                aiBubble.innerHTML = marked.parse(fullResponse) + '<span class="cursor-blink">|</span>';
            } else {
                aiBubble.textContent = fullResponse;
            }

            // Scroll to bottom
            const chatBody = document.getElementById('chat-messages');
            chatBody.scrollTop = chatBody.scrollHeight;
        }

        // Final render without cursor
        if (typeof marked !== 'undefined') {
            aiBubble.innerHTML = marked.parse(fullResponse);
            // Trigger MathJax render if available
            if (window.MathJax && window.MathJax.typesetPromise) {
                window.MathJax.typesetPromise([aiBubble]).catch(err => console.log('MathJax error:', err));
            }
        }

        // Add to history
        chatHistory.push({ role: 'assistant', content: fullResponse });

        // Refresh session list title preview
        loadChatSessions(currentChatPaperId);

    } catch (error) {
        console.error('Chat error:', error);
        const msg = (error && error.message) ? error.message : 'Error sending message.';
        aiBubble.innerHTML = `<span style="color: #fa5252;">${msg}</span>`;
    }
}

function appendChatMessage(role, text, isThinking = false) {
    const chatBody = document.getElementById('chat-messages');

    const rowDiv = document.createElement('div');
    rowDiv.className = `message-row ${role}`; // .user or .ai

    // Avatar
    const avatarDiv = document.createElement('div');
    avatarDiv.className = `message-avatar ${role}`;
    avatarDiv.innerHTML = role === 'user' ? '<i class="fas fa-user"></i>' : '<i class="fas fa-robot"></i>';

    // Bubble
    const bubbleDiv = document.createElement('div');
    bubbleDiv.className = 'message-bubble';

    if (!isThinking) {
        if (role === 'ai' && typeof marked !== 'undefined' && text) {
            bubbleDiv.innerHTML = marked.parse(text);
            if (window.MathJax && window.MathJax.typesetPromise) {
                // Defer MathJax to avoid blocking UI during initial render
                setTimeout(() => window.MathJax.typesetPromise([bubbleDiv]), 0);
            }
        } else {
            bubbleDiv.textContent = text;
        }
    }

    rowDiv.appendChild(avatarDiv);
    rowDiv.appendChild(bubbleDiv);

    chatBody.appendChild(rowDiv);
    chatBody.scrollTop = chatBody.scrollHeight;

    return rowDiv;
}

// Event listeners for Chat
onAppReady(() => {
    const commonPromptsBtn = document.getElementById('chat-common-prompts-btn');
    if (commonPromptsBtn) {
        commonPromptsBtn.addEventListener('click', showChatCommonPromptsManager);
    }

    const dropdown = document.getElementById('chat-prompt-dropdown');
    if (dropdown) {
        dropdown.addEventListener('mousedown', (e) => e.preventDefault());
        dropdown.addEventListener('mousemove', (e) => {
            const item = e.target.closest('.chat-prompt-item');
            if (!item) return;
            const idx = parseInt(item.dataset.index, 10);
            if (!isNaN(idx) && idx !== chatPromptDropdownState.activeIndex) {
                chatPromptDropdownState.activeIndex = idx;
                renderChatPromptDropdown();
            }
        });
        dropdown.addEventListener('click', (e) => {
            const item = e.target.closest('.chat-prompt-item');
            if (!item) return;
            const idx = parseInt(item.dataset.index, 10);
            if (!isNaN(idx)) selectChatPromptByIndex(idx);
        });
    }

    // Send button
    const sendBtn = document.getElementById('chat-send-btn');
    if (sendBtn) {
        sendBtn.addEventListener('click', sendChatMessage);
    }

    // New Session button
    const newSessionBtn = document.getElementById('chat-new-session-btn');
    if (newSessionBtn) {
        newSessionBtn.addEventListener('click', () => createNewSession(true));
    }

    // Textarea enter key
    const textarea = document.getElementById('chat-input');
    if (textarea) {
        const updateDropdownFromCursor = () => {
            const ctx = getChatSlashContext(textarea.value || '', textarea.selectionStart ?? (textarea.value || '').length);
            if (ctx.startIndex >= 0) openChatPromptDropdown(ctx);
            else closeChatPromptDropdown();
        };

        textarea.addEventListener('keydown', (e) => {
            if (e.isComposing || e.keyCode === 229) return;

            if (chatPromptDropdownState.open) {
                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    const max = (chatPromptDropdownState.items || []).length;
                    if (max) {
                        chatPromptDropdownState.activeIndex = (chatPromptDropdownState.activeIndex + 1) % max;
                        renderChatPromptDropdown();
                    }
                    return;
                }
                if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    const max = (chatPromptDropdownState.items || []).length;
                    if (max) {
                        chatPromptDropdownState.activeIndex = (chatPromptDropdownState.activeIndex - 1 + max) % max;
                        renderChatPromptDropdown();
                    }
                    return;
                }
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    selectChatPromptByIndex(chatPromptDropdownState.activeIndex);
                    return;
                }
                if (e.key === 'Escape') {
                    e.preventDefault();
                    closeChatPromptDropdown();
                    return;
                }
            }

            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendChatMessage();
                return;
            }
            if (e.key === 'Escape') {
                closeChatPromptDropdown();
            }
        });

        // Auto-resize textarea
        textarea.addEventListener('input', function () {
            this.style.height = 'auto';
            this.style.height = (this.scrollHeight) + 'px';
            if (this.value === '') {
                this.style.height = '';
            }
            updateDropdownFromCursor();
        });

        textarea.addEventListener('click', updateDropdownFromCursor);
        textarea.addEventListener('keyup', (e) => {
            if (e.isComposing || e.keyCode === 229) return;
            if (e.key === 'ArrowLeft' || e.key === 'ArrowRight' || e.key === 'Home' || e.key === 'End') {
                updateDropdownFromCursor();
            }
        });

        textarea.addEventListener('blur', () => {
            setTimeout(() => closeChatPromptDropdown(), 120);
        });
    }

    // Close button
    const closeBtn = document.getElementById('chat-modal-close');
    if (closeBtn) {
        closeBtn.addEventListener('click', closeChatModal);
    }

    // Close on click outside
    const modal = document.getElementById('chat-modal');
    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeChatModal();
            }
        });
    }
});
