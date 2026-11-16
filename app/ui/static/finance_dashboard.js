/**
 * Victor Finance & Bill Management Dashboard Controller
 * Fully integrated with Victor's Unified Financial Architecture:
 * REST API (/api/finance/*), Real-time WebSocket events (finance_update, dashboard_navigate),
 * and Victor Voice/Text Navigation Controller.
 */

(function () {
    'use strict';

    const FinanceDashboard = {
        activeTab: 'overview',
        currentPeriod: '',
        billFilter: 'all',
        categories: [],
        transactions: [],
        budgets: [],
        bills: [],
        subscriptions: [],
        summary: null,
        initialized: false,

        // =====================================================================
        // INITIALIZATION & LIFECYCLE
        // =====================================================================
        init() {
            if (this.initialized) return;
            this.initialized = true;

            // Set default period to current YYYY-MM
            const now = new Date();
            const yyyy = now.getFullYear();
            const mm = String(now.getMonth() + 1).padStart(2, '0');
            this.currentPeriod = `${yyyy}-${mm}`;

            const monthInput = document.getElementById('finMonthSelect');
            if (monthInput) {
                monthInput.value = this.currentPeriod;
                monthInput.addEventListener('change', (e) => {
                    this.currentPeriod = e.target.value || this.getDefaultPeriod();
                    this.loadAll();
                });
            }

            // Sync Button
            const syncBtn = document.getElementById('finSyncBtn');
            if (syncBtn) {
                syncBtn.addEventListener('click', () => {
                    this.loadAll();
                    this.showToast('Financial records synchronized.');
                });
            }

            // Return to Orb / Close Button
            const closeBtn = document.getElementById('finCloseBtn');
            if (closeBtn) {
                closeBtn.addEventListener('click', () => {
                    this.hide();
                    if (typeof window.openModuleView === 'function') {
                        window.openModuleView('dashboard');
                    }
                });
            }

            // Tab Navigation
            document.querySelectorAll('.fin-tab-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    this.switchTab(btn.dataset.tab);
                });
            });

            // Overview quick jumps
            const viewAllTx = document.getElementById('finOverviewViewAllTxBtn');
            if (viewAllTx) viewAllTx.addEventListener('click', () => this.switchTab('transactions'));
            const viewAllBills = document.getElementById('finOverviewViewAllBillsBtn');
            if (viewAllBills) viewAllBills.addEventListener('click', () => this.switchTab('bills'));

            // Modal openers
            this.bindModalTrigger('finOpenAddTxBtn', 'finModalAddTx');
            this.bindModalTrigger('finTxAddBtn', 'finModalAddTx');
            this.bindModalTrigger('finOpenAddBillBtn', 'finModalAddBill');
            this.bindModalTrigger('finAddBillTabBtn', 'finModalAddBill');
            this.bindModalTrigger('finOpenAddBudgetBtn', 'finModalAddBudget');
            this.bindModalTrigger('finOpenAddSubBtn', 'finModalAddSub');

            // Modal closers
            document.querySelectorAll('[data-close-modal]').forEach(el => {
                el.addEventListener('click', () => {
                    const modalId = el.getAttribute('data-close-modal');
                    this.closeModal(modalId);
                });
            });

            // Close modal when clicking on overlay background
            document.querySelectorAll('.fin-modal-overlay').forEach(overlay => {
                overlay.addEventListener('click', (e) => {
                    if (e.target === overlay) overlay.classList.add('hidden');
                });
            });

            // Forms bindings
            this.bindForms();

            // Filter bindings
            this.bindFilters();

            // Auto-refresh polling every 10s when finance view is visible as a fallback to WebSocket
            setInterval(() => {
                const view = document.getElementById('financeDashboardView');
                if (view && !view.classList.contains('hidden')) {
                    this.loadAll();
                }
            }, 10000);

            // Load initial data
            this.loadAll();
        },

        getDefaultPeriod() {
            const now = new Date();
            return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
        },

        // =====================================================================
        // VIEW VISIBILITY TOGGLING
        // =====================================================================
        show() {
            this.init();
            const view = document.getElementById('financeDashboardView');
            const grid = document.querySelector('.hud-command-grid');
            const quickActions = document.querySelector('.quick-actions-bar');
            const headerStrip = document.querySelector('.workspace-header-strip');
            const moduleDrawer = document.getElementById('moduleDrawer');

            if (view) view.classList.remove('hidden');
            if (grid) grid.classList.add('hidden');
            if (quickActions) quickActions.classList.add('hidden');
            if (headerStrip) headerStrip.classList.add('hidden');
            if (moduleDrawer) moduleDrawer.classList.add('hidden');

            document.querySelectorAll('.sidebar-item, .topnav-item').forEach(b => {
                b.classList.toggle('is-active', b.dataset.view === 'finance');
            });

            this.loadAll();
        },

        hide(restoreDashboard = true) {
            const view = document.getElementById('financeDashboardView');
            const grid = document.querySelector('.hud-command-grid');
            const quickActions = document.querySelector('.quick-actions-bar');
            const headerStrip = document.querySelector('.workspace-header-strip');

            if (view) view.classList.add('hidden');
            if (restoreDashboard) {
                if (grid) grid.classList.remove('hidden');
                if (quickActions) quickActions.classList.remove('hidden');
                if (headerStrip) headerStrip.classList.remove('hidden');
                document.querySelectorAll('.sidebar-item, .topnav-item').forEach(b => {
                    b.classList.toggle('is-active', b.dataset.view === 'dashboard');
                });
            }
        },

        switchTab(tabName) {
            this.activeTab = tabName;
            document.querySelectorAll('.fin-tab-btn').forEach(btn => {
                btn.classList.toggle('is-active', btn.dataset.tab === tabName);
            });
            document.querySelectorAll('.fin-tab-pane').forEach(pane => {
                pane.classList.remove('is-active');
            });

            const targetPane = document.getElementById(`finTab${tabName.charAt(0).toUpperCase() + tabName.slice(1)}`);
            if (targetPane) targetPane.classList.add('is-active');

            if (tabName === 'analytics') {
                this.renderAnalytics();
            }
        },

        bindModalTrigger(btnId, modalId) {
            const btn = document.getElementById(btnId);
            if (btn) {
                btn.addEventListener('click', () => {
                    this.populateCategoryDropdowns();
                    this.openModal(modalId);
                });
            }
        },

        openModal(modalId) {
            const modal = document.getElementById(modalId);
            if (modal) {
                modal.classList.remove('hidden');
                // Auto-fill today's date for date inputs
                const today = new Date().toISOString().split('T')[0];
                modal.querySelectorAll('input[type="date"]').forEach(inp => {
                    if (!inp.value) inp.value = today;
                });
            }
        },

        closeModal(modalId) {
            const modal = document.getElementById(modalId);
            if (modal) modal.classList.add('hidden');
        },

        // =====================================================================
        // DATA FETCHING (Unified REST API)
        // =====================================================================
        async loadAll() {
            const period = this.currentPeriod || this.getDefaultPeriod();
            try {
                const [catsRes, summaryRes, txRes, budgetsRes, billsRes, subsRes] = await Promise.all([
                    fetch('/api/finance/categories').then(r => r.json()).catch(() => ({ categories: [] })),
                    fetch(`/api/finance/summary?period=${encodeURIComponent(period)}`).then(r => r.json()).catch(() => null),
                    fetch(`/api/finance/transactions?limit=100`).then(r => r.json()).catch(() => ({ transactions: [] })),
                    fetch('/api/finance/budgets').then(r => r.json()).catch(() => ({ budgets: [] })),
                    fetch('/api/finance/bills').then(r => r.json()).catch(() => ({ bills: [] })),
                    fetch('/api/finance/subscriptions').then(r => r.json()).catch(() => ({ subscriptions: [] })),
                ]);

                this.categories = catsRes.categories || [];
                this.summary = summaryRes;
                this.transactions = txRes.transactions || [];
                this.budgets = budgetsRes.budgets || [];
                this.bills = billsRes.bills || [];
                this.subscriptions = subsRes.subscriptions || [];

                this.populateCategoryDropdowns();
                this.renderOverview();
                this.renderTransactions();
                this.renderCategories();
                this.renderBudgets();
                this.renderBills();
                this.renderSubscriptions();
                this.renderAnalytics();
            } catch (err) {
                console.error('[Victor Finance] Failed to load financial data:', err);
            }
        },

        populateCategoryDropdowns() {
            const selects = [
                document.getElementById('finTxCategoryFilter'),
                document.getElementById('finTxCategory'),
                document.getElementById('finBillCategory'),
                document.getElementById('finBudgetCategory'),
                document.getElementById('finSubCategory'),
            ];

            const cats = this.categories.length > 0 ? this.categories : [
                'Food', 'Shopping', 'Travel', 'Education', 'Healthcare',
                'Bills', 'Rent', 'Utilities', 'Entertainment', 'Subscriptions',
                'Personal Care', 'Electronics', 'Investments', 'Income', 'Others'
            ];

            selects.forEach(select => {
                if (!select) return;
                const isFilter = select.id.includes('Filter');
                const isBudget = select.id === 'finBudgetCategory';
                const currentVal = select.value;

                let opts = '';
                if (isFilter) {
                    opts += '<option value="">All Categories</option>';
                } else if (isBudget) {
                    opts += '<option value="All">All Categories (Overall Budget)</option>';
                }

                cats.forEach(c => {
                    opts += `<option value="${c}">${c}</option>`;
                });

                select.innerHTML = opts;
                if (currentVal) select.value = currentVal;
            });
        },

        // =====================================================================
        // RENDERING TABS
        // =====================================================================
        renderOverview() {
            if (!this.summary) return;

            const totalExpenses = this.summary.total_expenses || 0;
            const totalIncome = this.summary.total_income || 0;
            const netSavings = this.summary.net_savings || 0;
            const savingsRate = this.summary.savings_rate || 0;
            const remainingBudget = this.summary.remaining_budget;

            const elExpenses = document.getElementById('finOverviewExpenses');
            const elIncome = document.getElementById('finOverviewIncome');
            const elBudget = document.getElementById('finOverviewBudget');
            const elSavings = document.getElementById('finOverviewSavings');
            const elSavingsBadge = document.getElementById('finSavingsRateBadge');
            const elBudgetBadge = document.getElementById('finBudgetStatusBadge');

            if (elExpenses) elExpenses.textContent = this.formatCurrency(totalExpenses);
            if (elIncome) elIncome.textContent = this.formatCurrency(totalIncome);
            if (elSavings) {
                elSavings.textContent = this.formatCurrency(netSavings);
                elSavings.style.color = netSavings >= 0 ? 'var(--accent-emerald, #00E5A8)' : 'var(--accent-rose, #FF4565)';
            }
            if (elSavingsBadge) {
                elSavingsBadge.textContent = `${savingsRate.toFixed(1)}% RATE`;
            }

            if (elBudget) {
                if (remainingBudget !== null && remainingBudget !== undefined) {
                    elBudget.textContent = this.formatCurrency(remainingBudget);
                    if (remainingBudget < 0) {
                        elBudget.style.color = 'var(--accent-rose, #FF4565)';
                        if (elBudgetBadge) {
                            elBudgetBadge.textContent = 'EXCEEDED';
                            elBudgetBadge.className = 'fin-metric-badge badge-expense';
                        }
                    } else if (remainingBudget < 2000) {
                        elBudget.style.color = 'var(--accent-amber, #FFB547)';
                        if (elBudgetBadge) {
                            elBudgetBadge.textContent = 'TIGHT';
                            elBudgetBadge.className = 'fin-metric-badge badge-budget';
                        }
                    } else {
                        elBudget.style.color = 'var(--accent-cyan, #00D9FF)';
                        if (elBudgetBadge) {
                            elBudgetBadge.textContent = 'SAFE';
                            elBudgetBadge.className = 'fin-metric-badge badge-income';
                        }
                    }
                } else {
                    elBudget.textContent = 'No budget set';
                    if (elBudgetBadge) elBudgetBadge.textContent = 'INACTIVE';
                }
            }

            // Alerts Banner
            const banner = document.getElementById('finBudgetAlertBanner');
            const alertText = document.getElementById('finBudgetAlertText');
            if (banner && alertText) {
                const alerts = [];
                if (remainingBudget !== null && remainingBudget < 0) {
                    alerts.push(`Overall monthly budget has been exceeded by ${this.formatCurrency(Math.abs(remainingBudget))}.`);
                }
                const overdueBills = this.bills.filter(b => b.status === 'overdue');
                if (overdueBills.length > 0) {
                    alerts.push(`You have ${overdueBills.length} overdue bill(s) requiring immediate payment.`);
                }

                if (alerts.length > 0) {
                    alertText.innerHTML = alerts.join('<br>');
                    banner.classList.remove('hidden');
                } else {
                    banner.classList.add('hidden');
                }
            }

            // Recent Transactions List (top 5)
            const recentTxList = document.getElementById('finOverviewRecentTxList');
            if (recentTxList) {
                const recent = this.transactions.slice(0, 5);
                if (recent.length === 0) {
                    recentTxList.innerHTML = '<div class="fin-empty-state">No transactions recorded yet.</div>';
                } else {
                    recentTxList.innerHTML = recent.map(tx => {
                        const txId = tx.id || tx.transaction_id || '';
                        return `
                        <div class="fin-list-item">
                            <div class="fin-item-main">
                                <div class="fin-item-title">
                                    ${txId ? `<span class="fin-id-badge" style="margin-right: 6px; font-size: 10px;">${this.escapeHtml(txId)}</span>` : ''}
                                    ${this.escapeHtml(tx.merchant || tx.description || 'Transaction')}
                                </div>
                                <div class="fin-item-meta">${this.formatDate(tx.date)} &bull; ${this.escapeHtml(tx.category)} &bull; ${this.escapeHtml(tx.payment_method || 'UPI')}</div>
                            </div>
                            <div class="fin-item-amount ${tx.transaction_type === 'income' ? 'is-income' : 'is-expense'}">
                                ${tx.transaction_type === 'income' ? '+' : '-'}${this.formatCurrency(tx.amount)}
                            </div>
                        </div>
                    `;}).join('');
                }
            }

            // Upcoming & Pending Bills List (top 5)
            const upcomingBillsList = document.getElementById('finOverviewUpcomingBillsList');
            if (upcomingBillsList) {
                const pendingBills = this.bills.filter(b => b.status !== 'paid').slice(0, 5);
                if (pendingBills.length === 0) {
                    upcomingBillsList.innerHTML = '<div class="fin-empty-state">No upcoming bills due. All settled!</div>';
                } else {
                    upcomingBillsList.innerHTML = pendingBills.map(b => `
                        <div class="fin-list-item">
                            <div class="fin-item-main">
                                <div class="fin-item-title">${this.escapeHtml(b.title)}</div>
                                <div class="fin-item-meta">Due: ${this.formatDate(b.due_date)} &bull; ${this.escapeHtml(b.category)}</div>
                            </div>
                            <div class="fin-item-right">
                                <span class="fin-status-badge is-${b.status}">${b.status.toUpperCase()}</span>
                                <span class="fin-item-amount is-expense">${this.formatCurrency(b.amount)}</span>
                                <button class="fin-btn-sm fin-btn-cyan" data-pay-bill="${b.id}" data-pay-title="${this.escapeHtml(b.title)}" type="button">Pay</button>
                            </div>
                        </div>
                    `).join('');

                    upcomingBillsList.querySelectorAll('[data-pay-bill]').forEach(btn => {
                        btn.addEventListener('click', () => {
                            this.openPayBillModal(btn.dataset.payBill, btn.dataset.payTitle);
                        });
                    });
                }
            }
        },

        renderTransactions() {
            const tableBody = document.getElementById('finTxTableBody');
            if (!tableBody) return;

            const search = (document.getElementById('finTxSearchInput')?.value || '').toLowerCase().trim();
            const typeFilter = document.getElementById('finTxTypeFilter')?.value || '';
            const catFilter = document.getElementById('finTxCategoryFilter')?.value || '';
            const methodFilter = document.getElementById('finTxMethodFilter')?.value || '';

            let filtered = this.transactions.filter(tx => {
                if (typeFilter && tx.transaction_type !== typeFilter) return false;
                if (catFilter && tx.category !== catFilter) return false;
                if (methodFilter && (tx.payment_method || '').toLowerCase() !== methodFilter.toLowerCase()) return false;
                if (search) {
                    const text = `${tx.merchant} ${tx.description} ${tx.notes} ${tx.category}`.toLowerCase();
                    if (!text.includes(search)) return false;
                }
                return true;
            });

            if (filtered.length === 0) {
                tableBody.innerHTML = `<tr><td colspan="8" class="fin-empty-state">No matching transactions found.</td></tr>`;
                return;
            }

            tableBody.innerHTML = filtered.map(tx => {
                const txId = tx.id || tx.transaction_id || '';
                return `
                <tr data-tx-id="${txId}">
                    <td class="fin-tx-id">
                        <span class="fin-id-badge">${this.escapeHtml(txId)}</span>
                    </td>
                    <td>${this.formatDate(tx.date)}</td>
                    <td>
                        <span class="fin-type-pill is-${tx.transaction_type}">
                            ${tx.transaction_type.toUpperCase()}
                        </span>
                    </td>
                    <td>
                        <strong>${this.escapeHtml(tx.merchant || '—')}</strong>
                        ${tx.description ? `<div class="fin-cell-sub">${this.escapeHtml(tx.description)}</div>` : ''}
                    </td>
                    <td><span class="fin-cat-pill">${this.escapeHtml(tx.category)}</span></td>
                    <td>${this.escapeHtml(tx.payment_method || 'UPI')}</td>
                    <td style="text-align: right;" class="${tx.transaction_type === 'income' ? 'fin-amount-income' : 'fin-amount-expense'}">
                        ${tx.transaction_type === 'income' ? '+' : '-'}${this.formatCurrency(tx.amount)}
                    </td>
                    <td style="text-align: center;">
                        <button class="fin-action-icon-btn delete-tx" data-id="${txId}" title="Delete Transaction ${this.escapeHtml(txId)}" type="button">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                        </button>
                    </td>
                </tr>
            `;}).join('');

            tableBody.querySelectorAll('.delete-tx').forEach(btn => {
                btn.addEventListener('click', () => this.deleteTransaction(btn.dataset.id));
            });
        },

        renderCategories() {
            const grid = document.getElementById('finCategoryGrid');
            const countBadge = document.getElementById('finCategoryCountBadge');
            if (!grid) return;

            const breakdown = this.summary?.category_breakdown || {};
            const totalExpense = this.summary?.total_expenses || 1;
            const entries = Object.entries(breakdown);

            if (countBadge) countBadge.textContent = `${entries.length} CATEGORIES`;

            if (entries.length === 0) {
                grid.innerHTML = '<div class="fin-empty-state">No category spending recorded for this period.</div>';
                return;
            }

            // Sort descending by spend
            entries.sort((a, b) => b[1] - a[1]);

            grid.innerHTML = entries.map(([cat, amount]) => {
                const pct = Math.min(100, Math.round((amount / (totalExpense || 1)) * 100));
                return `
                    <div class="glass-card fin-cat-card" data-category="${this.escapeHtml(cat)}">
                        <div class="fin-cat-card-header">
                            <span class="fin-cat-card-name">${this.escapeHtml(cat)}</span>
                            <span class="fin-cat-card-amount">${this.formatCurrency(amount)}</span>
                        </div>
                        <div class="fin-progress-track">
                            <div class="fin-progress-bar fin-bar-cyan" style="width: ${pct}%;"></div>
                        </div>
                        <div class="fin-cat-card-sub">
                            <span>${pct}% of total spend</span>
                        </div>
                    </div>
                `;
            }).join('');

            // Clicking a category card switches to Transactions tab filtered by that category
            grid.querySelectorAll('.fin-cat-card').forEach(card => {
                card.addEventListener('click', () => {
                    const cat = card.dataset.category;
                    const catSelect = document.getElementById('finTxCategoryFilter');
                    if (catSelect) catSelect.value = cat;
                    this.switchTab('transactions');
                    this.renderTransactions();
                });
            });
        },

        renderBudgets() {
            const container = document.getElementById('finBudgetsList');
            if (!container) return;

            if (this.budgets.length === 0) {
                container.innerHTML = `
                    <div class="fin-empty-state">
                        No budgets configured yet. Click "+ Set New Budget" to create limits for overall spending or specific categories.
                    </div>
                `;
                return;
            }

            const breakdown = this.summary?.category_breakdown || {};
            const totalExpense = this.summary?.total_expenses || 0;

            container.innerHTML = this.budgets.map(b => {
                const categoryName = b.category || 'Overall';
                const isOverall = categoryName.toLowerCase() === 'all' || categoryName.toLowerCase() === 'overall';
                const spent = b.spent_amount !== undefined ? b.spent_amount : (isOverall ? totalExpense : (breakdown[categoryName] || 0));
                const limit = b.limit_amount || 0;
                const remaining = b.remaining_amount !== undefined ? b.remaining_amount : (limit - spent);
                const pct = b.percentage_used !== undefined ? Math.round(b.percentage_used) : Math.round((spent / (limit || 1)) * 100);
                const periodStr = (b.period || 'monthly').toUpperCase();
                const budgetId = b.id || b.budget_id;

                let barColorClass = 'fin-bar-cyan';
                let statusText = `${pct}% utilized`;
                if (pct >= 100) {
                    barColorClass = 'fin-bar-rose';
                    statusText = `EXCEEDED by ${this.formatCurrency(Math.abs(remaining))}`;
                } else if (pct >= 75) {
                    barColorClass = 'fin-bar-amber';
                    statusText = `WARNING (${pct}%)`;
                }

                return `
                    <div class="glass-card fin-budget-card">
                        <div class="fin-budget-header">
                            <div>
                                <h4 class="fin-budget-title">${this.escapeHtml(categoryName)} Budget</h4>
                                <div class="fin-budget-period">${periodStr} &bull; Limit: ${this.formatCurrency(limit)}</div>
                            </div>
                            <button class="fin-action-icon-btn delete-budget" data-id="${budgetId}" title="Delete Budget" type="button">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                            </button>
                        </div>
                        <div class="fin-budget-numbers">
                            <div>
                                <span class="fin-budget-label">Spent</span>
                                <span class="fin-budget-val is-spent">${this.formatCurrency(spent)}</span>
                            </div>
                            <div style="text-align: right;">
                                <span class="fin-budget-label">Remaining</span>
                                <span class="fin-budget-val ${remaining >= 0 ? 'is-safe' : 'is-exceeded'}">${this.formatCurrency(remaining)}</span>
                            </div>
                        </div>
                        <div class="fin-progress-track">
                            <div class="fin-progress-bar ${barColorClass}" style="width: ${Math.min(100, Math.max(0, pct))}%;"></div>
                        </div>
                        <div class="fin-budget-footer">${statusText}</div>
                    </div>
                `;
            }).join('');

            container.querySelectorAll('.delete-budget').forEach(btn => {
                btn.addEventListener('click', () => this.deleteBudget(btn.dataset.id));
            });
        },

        renderBills() {
            const grid = document.getElementById('finBillsGrid');
            if (!grid) return;

            let bills = this.bills;
            if (this.billFilter === 'pending') {
                bills = bills.filter(b => b.status === 'pending');
            } else if (this.billFilter === 'overdue') {
                bills = bills.filter(b => b.status === 'overdue');
            } else if (this.billFilter === 'paid') {
                bills = bills.filter(b => b.status === 'paid');
            }

            if (bills.length === 0) {
                grid.innerHTML = `<div class="fin-empty-state">No bills found for "${this.billFilter}" status.</div>`;
                return;
            }

            grid.innerHTML = bills.map(b => `
                <div class="glass-card fin-bill-card">
                    <div class="fin-bill-header">
                        <div>
                            <h4 class="fin-bill-title">${this.escapeHtml(b.title)}</h4>
                            <div class="fin-bill-meta">${this.escapeHtml(b.category)} &bull; ${b.recurrence.toUpperCase()}</div>
                        </div>
                        <span class="fin-status-badge is-${b.status}">${b.status.toUpperCase()}</span>
                    </div>
                    <div class="fin-bill-amount-row">
                        <span class="fin-bill-amount">${this.formatCurrency(b.amount)}</span>
                        <span class="fin-bill-duedate">Due: ${this.formatDate(b.due_date)}</span>
                    </div>
                    <div class="fin-bill-actions">
                        ${b.status !== 'paid' ? `
                            <button class="fin-btn-sm fin-btn-cyan pay-bill-btn" data-id="${b.id}" data-title="${this.escapeHtml(b.title)}" type="button">Mark Paid</button>
                            <button class="fin-btn-sm fin-btn-secondary postpone-bill-btn" data-id="${b.id}" type="button">Postpone</button>
                        ` : `
                            <span class="fin-paid-stamp">✓ Paid on ${this.formatDate(b.updated_at || b.due_date)}</span>
                        `}
                        <button class="fin-action-icon-btn delete-bill-btn" data-id="${b.id}" title="Delete Bill" type="button">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                        </button>
                    </div>
                </div>
            `).join('');

            grid.querySelectorAll('.pay-bill-btn').forEach(btn => {
                btn.addEventListener('click', () => this.openPayBillModal(btn.dataset.id, btn.dataset.title));
            });

            grid.querySelectorAll('.postpone-bill-btn').forEach(btn => {
                btn.addEventListener('click', () => this.postponeBill(btn.dataset.id));
            });

            grid.querySelectorAll('.delete-bill-btn').forEach(btn => {
                btn.addEventListener('click', () => this.deleteBill(btn.dataset.id));
            });
        },

        renderSubscriptions() {
            const grid = document.getElementById('finSubsGrid');
            const burnEl = document.getElementById('finSubsBurnRate');
            const annualEl = document.getElementById('finSubsAnnualRate');

            // Calculate monthly burn
            let monthlyBurn = 0;
            this.subscriptions.forEach(s => {
                if (s.status === 'active') {
                    if (s.billing_cycle === 'yearly') {
                        monthlyBurn += s.amount / 12;
                    } else if (s.billing_cycle === 'quarterly') {
                        monthlyBurn += s.amount / 3;
                    } else {
                        monthlyBurn += s.amount;
                    }
                }
            });

            if (burnEl) burnEl.textContent = `${this.formatCurrency(monthlyBurn)} / month`;
            if (annualEl) annualEl.textContent = `${this.formatCurrency(monthlyBurn * 12)} annualized recurring run rate`;

            if (!grid) return;

            if (this.subscriptions.length === 0) {
                grid.innerHTML = '<div class="fin-empty-state">No active subscriptions configured. Track Netflix, Spotify, Prime, etc.</div>';
                return;
            }

            grid.innerHTML = this.subscriptions.map(s => `
                <div class="glass-card fin-sub-card">
                    <div class="fin-sub-header">
                        <div>
                            <h4 class="fin-sub-title">${this.escapeHtml(s.service_name)}</h4>
                            <div class="fin-sub-meta">${s.billing_cycle.toUpperCase()} &bull; ${this.escapeHtml(s.category || 'Subscriptions')}</div>
                        </div>
                        <span class="fin-status-badge is-${s.status}">${s.status.toUpperCase()}</span>
                    </div>
                    <div class="fin-sub-amount-row">
                        <span class="fin-sub-amount">${this.formatCurrency(s.amount)}</span>
                        <span class="fin-sub-renewal">Renewal: ${this.formatDate(s.next_renewal_date)}</span>
                    </div>
                    <div class="fin-sub-actions">
                        <button class="fin-action-icon-btn delete-sub-btn" data-id="${s.id}" title="Delete Subscription" type="button">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                        </button>
                    </div>
                </div>
            `).join('');

            grid.querySelectorAll('.delete-sub-btn').forEach(btn => {
                btn.addEventListener('click', () => this.deleteSubscription(btn.dataset.id));
            });
        },

        renderAnalytics(period) {
            if (!this.summary) return;

            const periodSelect = document.getElementById('finAnalyticsPeriodSelect');
            const selectedPeriod = period || (periodSelect ? periodSelect.value : 'monthly');

            const inflowEl = document.getElementById('finAnaInflow');
            const outflowEl = document.getElementById('finAnaOutflow');
            const savingsEl = document.getElementById('finAnaSavings');
            const burnRateEl = document.getElementById('finAnaBurnRate');

            let mult = 1.0;
            let burnLabel = '/day';
            const daysInMonth = 30;
            const daily = (this.summary.total_expenses || 0) / daysInMonth;

            if (selectedPeriod === 'weekly') {
                mult = 7.0 / daysInMonth;
                burnLabel = '/week';
            } else if (selectedPeriod === 'annual') {
                mult = 12.0;
                burnLabel = '/year';
            }

            const inflowVal = (this.summary.total_income || 0) * mult;
            const outflowVal = (this.summary.total_expenses || 0) * mult;
            const savingsVal = (this.summary.net_savings || 0) * mult;
            const burnVal = selectedPeriod === 'weekly' ? (daily * 7) : (selectedPeriod === 'annual' ? (daily * 365) : daily);

            if (inflowEl) inflowEl.textContent = this.formatCurrency(inflowVal);
            if (outflowEl) outflowEl.textContent = this.formatCurrency(outflowVal);
            if (savingsEl) savingsEl.textContent = this.formatCurrency(savingsVal);
            if (burnRateEl) burnRateEl.textContent = `${this.formatCurrency(burnVal)}${burnLabel}`;

            // Set up default comparison inputs if empty
            const m1 = document.getElementById('finCmpMonth1');
            const m2 = document.getElementById('finCmpMonth2');
            if (m1 && !m1.value) {
                const now = new Date();
                m1.value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
            }
            if (m2 && !m2.value) {
                const prev = new Date();
                prev.setMonth(prev.getMonth() - 1);
                m2.value = `${prev.getFullYear()}-${String(prev.getMonth() + 1).padStart(2, '0')}`;
            }
        },

        // =====================================================================
        // ACTIONS & FORM SUBMISSIONS
        // =====================================================================
        bindForms() {
            // 1. Add Transaction Form
            const formTx = document.getElementById('finFormAddTx');
            if (formTx) {
                formTx.addEventListener('submit', async (e) => {
                    e.preventDefault();
                    const payload = {
                        transaction_type: document.getElementById('finTxType').value,
                        amount: parseFloat(document.getElementById('finTxAmount').value),
                        category: document.getElementById('finTxCategory').value,
                        merchant: document.getElementById('finTxMerchant').value.trim(),
                        date: document.getElementById('finTxDate').value,
                        payment_method: document.getElementById('finTxMethod').value,
                        description: document.getElementById('finTxDesc').value.trim(),
                    };

                    try {
                        const res = await fetch('/api/finance/transactions', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload),
                        });
                        if (res.ok) {
                            this.closeModal('finModalAddTx');
                            formTx.reset();
                            this.showToast('Transaction recorded successfully.');
                            this.loadAll();
                        } else {
                            const err = await res.json();
                            alert(err.detail || 'Failed to save transaction');
                        }
                    } catch (err) {
                        console.error('Error saving transaction:', err);
                    }
                });
            }

            // 2. Add Bill Form
            const formBill = document.getElementById('finFormAddBill');
            if (formBill) {
                formBill.addEventListener('submit', async (e) => {
                    e.preventDefault();
                    const payload = {
                        title: document.getElementById('finBillTitle').value.trim(),
                        amount: parseFloat(document.getElementById('finBillAmount').value),
                        due_date: document.getElementById('finBillDueDate').value,
                        category: document.getElementById('finBillCategory').value || 'Bills',
                        recurrence: document.getElementById('finBillRecurrence').value,
                        payment_method: document.getElementById('finBillMethod').value.trim() || 'UPI',
                    };

                    try {
                        const res = await fetch('/api/finance/bills', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload),
                        });
                        if (res.ok) {
                            this.closeModal('finModalAddBill');
                            formBill.reset();
                            this.showToast('Bill scheduled with proactive reminders.');
                            this.loadAll();
                        } else {
                            const err = await res.json();
                            alert(err.detail || 'Failed to save bill');
                        }
                    } catch (err) {
                        console.error('Error saving bill:', err);
                    }
                });
            }

            // 3. Set Budget Form
            const formBudget = document.getElementById('finFormAddBudget');
            if (formBudget) {
                formBudget.addEventListener('submit', async (e) => {
                    e.preventDefault();
                    const payload = {
                        category: document.getElementById('finBudgetCategory').value,
                        period: document.getElementById('finBudgetPeriod').value,
                        limit_amount: parseFloat(document.getElementById('finBudgetLimit').value),
                    };

                    try {
                        const res = await fetch('/api/finance/budgets', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload),
                        });
                        if (res.ok) {
                            this.closeModal('finModalAddBudget');
                            formBudget.reset();
                            this.showToast('Budget configured.');
                            this.loadAll();
                        } else {
                            const err = await res.json();
                            alert(err.detail || 'Failed to save budget');
                        }
                    } catch (err) {
                        console.error('Error saving budget:', err);
                    }
                });
            }

            // 4. Add Subscription Form
            const formSub = document.getElementById('finFormAddSub');
            if (formSub) {
                formSub.addEventListener('submit', async (e) => {
                    e.preventDefault();
                    const payload = {
                        service_name: document.getElementById('finSubName').value.trim(),
                        amount: parseFloat(document.getElementById('finSubAmount').value),
                        billing_cycle: document.getElementById('finSubCycle').value,
                        next_renewal_date: document.getElementById('finSubRenewal').value,
                        category: document.getElementById('finSubCategory').value || 'Subscriptions',
                        payment_method: document.getElementById('finSubMethod').value.trim() || 'Auto-debit',
                    };

                    try {
                        const res = await fetch('/api/finance/subscriptions', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(payload),
                        });
                        if (res.ok) {
                            this.closeModal('finModalAddSub');
                            formSub.reset();
                            this.showToast('Subscription tracked.');
                            this.loadAll();
                        } else {
                            const err = await res.json();
                            alert(err.detail || 'Failed to save subscription');
                        }
                    } catch (err) {
                        console.error('Error saving subscription:', err);
                    }
                });
            }

            // 5. Pay Bill Form
            const formPay = document.getElementById('finFormPayBill');
            if (formPay) {
                formPay.addEventListener('submit', async (e) => {
                    e.preventDefault();
                    const billId = document.getElementById('finPayBillId').value;
                    const method = document.getElementById('finPayBillMethod').value;

                    try {
                        const res = await fetch(`/api/finance/bills/${billId}/pay?payment_method=${encodeURIComponent(method)}`, {
                            method: 'POST',
                        });
                        if (res.ok) {
                            this.closeModal('finModalPayBill');
                            this.showToast('Bill marked as paid & expense recorded.');
                            this.loadAll();
                        } else {
                            const err = await res.json();
                            alert(err.detail || 'Failed to record bill payment');
                        }
                    } catch (err) {
                        console.error('Error recording payment:', err);
                    }
                });
            }

            // 6. Add Custom Category Form
            const formCat = document.getElementById('finAddCategoryForm');
            if (formCat) {
                formCat.addEventListener('submit', async (e) => {
                    e.preventDefault();
                    const name = document.getElementById('finNewCatName').value.trim();
                    const subsRaw = document.getElementById('finNewCatSubs').value.trim();
                    const subcategories = subsRaw ? subsRaw.split(',').map(s => s.trim()).filter(Boolean) : [];

                    try {
                        const res = await fetch('/api/finance/categories', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ name, subcategories }),
                        });
                        if (res.ok) {
                            formCat.reset();
                            this.showToast(`Category '${name}' created.`);
                            this.loadAll();
                        } else {
                            const err = await res.json();
                            alert(err.detail || 'Failed to create category');
                        }
                    } catch (err) {
                        console.error('Error creating category:', err);
                    }
                });
            }

            // 7. Comparison Button
            const cmpBtn = document.getElementById('finRunComparisonBtn');
            if (cmpBtn) {
                cmpBtn.addEventListener('click', async () => {
                    const m1 = document.getElementById('finCmpMonth1').value;
                    const m2 = document.getElementById('finCmpMonth2').value;
                    if (!m1 || !m2) {
                        alert('Please select both months to compare.');
                        return;
                    }
                    try {
                        const res = await fetch(`/api/finance/comparison?month1=${encodeURIComponent(m1)}&month2=${encodeURIComponent(m2)}`);
                        const data = await res.json();
                        this.renderComparisonResult(data);
                    } catch (err) {
                        console.error('Error running comparison:', err);
                    }
                });
            }
        },

        bindFilters() {
            const searchInput = document.getElementById('finTxSearchInput');
            const typeFilter = document.getElementById('finTxTypeFilter');
            const catFilter = document.getElementById('finTxCategoryFilter');
            const methodFilter = document.getElementById('finTxMethodFilter');
            const resetBtn = document.getElementById('finTxResetFiltersBtn');

            if (searchInput) searchInput.addEventListener('input', () => this.renderTransactions());
            if (typeFilter) typeFilter.addEventListener('change', () => this.renderTransactions());
            if (catFilter) catFilter.addEventListener('change', () => this.renderTransactions());
            if (methodFilter) methodFilter.addEventListener('change', () => this.renderTransactions());

            const analyticsPeriodSelect = document.getElementById('finAnalyticsPeriodSelect');
            if (analyticsPeriodSelect) {
                analyticsPeriodSelect.addEventListener('change', () => {
                    this.renderAnalytics(analyticsPeriodSelect.value);
                });
            }

            if (resetBtn) {
                resetBtn.addEventListener('click', () => {
                    if (searchInput) searchInput.value = '';
                    if (typeFilter) typeFilter.value = '';
                    if (catFilter) catFilter.value = '';
                    if (methodFilter) methodFilter.value = '';
                    this.renderTransactions();
                });
            }

            // Bill status pills
            document.querySelectorAll('[data-bill-filter]').forEach(pill => {
                pill.addEventListener('click', () => {
                    document.querySelectorAll('[data-bill-filter]').forEach(p => p.classList.remove('is-active'));
                    pill.classList.add('is-active');
                    this.billFilter = pill.dataset.billFilter;
                    this.renderBills();
                });
            });
        },

        openPayBillModal(billId, billTitle) {
            const inputId = document.getElementById('finPayBillId');
            const promptEl = document.getElementById('finPayBillPrompt');
            if (inputId) inputId.value = billId;
            if (promptEl) promptEl.textContent = `Confirm marking "${billTitle}" as paid:`;
            this.openModal('finModalPayBill');
        },

        async postponeBill(billId) {
            const daysStr = prompt('Enter number of days to postpone (e.g. 3):', '3');
            if (!daysStr) return;
            const days = parseInt(daysStr, 10);
            if (isNaN(days) || days <= 0) {
                alert('Please enter a valid positive number of days.');
                return;
            }
            try {
                const res = await fetch(`/api/finance/bills/${billId}/postpone?days=${days}`, { method: 'POST' });
                if (res.ok) {
                    this.showToast(`Bill postponed by ${days} day(s).`);
                    this.loadAll();
                } else {
                    const err = await res.json();
                    alert(err.detail || 'Failed to postpone bill');
                }
            } catch (err) {
                console.error('Error postponing bill:', err);
            }
        },

        async deleteTransaction(txId) {
            if (!confirm(`Are you sure you want to delete transaction ${txId}?`)) return;
            try {
                const res = await fetch(`/api/finance/transactions/${encodeURIComponent(txId)}`, { method: 'DELETE' });
                if (res.ok) {
                    this.showToast(`Transaction ${txId} deleted.`);
                    this.loadAll();
                } else {
                    const err = await res.json().catch(() => ({}));
                    alert(`Failed to delete transaction: ${err.detail || err.error || 'Not found'}`);
                }
            } catch (err) {
                console.error('Error deleting transaction:', err);
            }
        },

        async deleteBudget(budgetId) {
            if (!confirm('Are you sure you want to delete this budget limit?')) return;
            try {
                const res = await fetch(`/api/finance/budgets/${budgetId}`, { method: 'DELETE' });
                if (res.ok) {
                    this.showToast('Budget deleted.');
                    this.loadAll();
                }
            } catch (err) {
                console.error('Error deleting budget:', err);
            }
        },

        async deleteBill(billId) {
            if (!confirm('Are you sure you want to delete this bill? Associated reminders will also be cancelled.')) return;
            try {
                const res = await fetch(`/api/finance/bills/${billId}`, { method: 'DELETE' });
                if (res.ok) {
                    this.showToast('Bill deleted.');
                    this.loadAll();
                }
            } catch (err) {
                console.error('Error deleting bill:', err);
            }
        },

        async deleteSubscription(subId) {
            if (!confirm('Are you sure you want to stop tracking this subscription?')) return;
            try {
                const res = await fetch(`/api/finance/subscriptions/${subId}`, { method: 'DELETE' });
                if (res.ok) {
                    this.showToast('Subscription deleted.');
                    this.loadAll();
                }
            } catch (err) {
                console.error('Error deleting subscription:', err);
            }
        },

        renderComparisonResult(data) {
            const out = document.getElementById('finComparisonOutput');
            if (!out) return;

            const m1 = data.month1;
            const m2 = data.month2;
            const diff = data.diff;
            const pct = data.pct_change;

            let diffText = '';
            if (diff > 0) {
                diffText = `<span style="color: var(--accent-rose, #FF4565);">+${this.formatCurrency(diff)} (+${pct.toFixed(1)}% higher spending in ${m1})</span>`;
            } else if (diff < 0) {
                diffText = `<span style="color: var(--accent-emerald, #00E5A8);">${this.formatCurrency(diff)} (${pct.toFixed(1)}% lower spending in ${m1})</span>`;
            } else {
                diffText = `<span>Identical spending in both periods.</span>`;
            }

            const catDiffs = data.category_diffs || {};
            const catRows = Object.entries(catDiffs).map(([c, d]) => `
                <tr>
                    <td><strong>${this.escapeHtml(c)}</strong></td>
                    <td style="text-align: right; color: ${d > 0 ? 'var(--accent-rose)' : 'var(--accent-emerald)'};">
                        ${d > 0 ? '+' : ''}${this.formatCurrency(d)}
                    </td>
                </tr>
            `).join('');

            out.innerHTML = `
                <div class="fin-cmp-card">
                    <div class="fin-cmp-header">
                        <h4>Delta Summary: ${m1} vs ${m2}</h4>
                        <div class="fin-cmp-diff">${diffText}</div>
                    </div>
                    <table class="fin-table" style="margin-top: 1rem;">
                        <thead>
                            <tr>
                                <th>Category</th>
                                <th style="text-align: right;">Variance (${m1} &minus; ${m2})</th>
                            </tr>
                        </thead>
                        <tbody>${catRows || '<tr><td colspan="2" class="fin-empty-state">No category shifts detected.</td></tr>'}</tbody>
                    </table>
                </div>
            `;
        },

        // =====================================================================
        // REAL-TIME NAVIGATION & EVENT HANDLERS
        // =====================================================================
        handleNavigation(tab, filters) {
            console.log('[Victor Finance] Dashboard navigation requested:', tab, filters);
            this.show();
            if (tab) this.switchTab(tab);

            if (filters) {
                if (filters.category) {
                    const catSelect = document.getElementById('finTxCategoryFilter');
                    if (catSelect) catSelect.value = filters.category;
                    this.renderTransactions();
                }
                if (filters.month || filters.period) {
                    const periodVal = filters.month || filters.period;
                    const monthInput = document.getElementById('finMonthSelect');
                    if (monthInput) monthInput.value = periodVal;
                    this.currentPeriod = periodVal;
                    this.loadAll();
                }
            }
        },

        handleUpdate(event) {
            console.log('[Victor Finance] Real-time financial update event received:', event);
            this.loadAll();
            if (event && event.action) {
                const act = String(event.action).replace(/_/g, ' ');
                this.showToast(`Updated: ${act}`);
            }
        },

        // =====================================================================
        // UTILITY HELPERS
        // =====================================================================
        formatCurrency(amount) {
            const num = Number(amount || 0);
            return '₹' + num.toLocaleString('en-IN', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
            });
        },

        formatDate(dateStr) {
            if (!dateStr) return '—';
            try {
                const d = new Date(dateStr);
                if (isNaN(d.getTime())) return dateStr;
                return d.toLocaleDateString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    year: 'numeric'
                });
            } catch (_) {
                return dateStr;
            }
        },

        escapeHtml(str) {
            if (!str) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        },

        showToast(message) {
            if (typeof window.addHudNotification === 'function') {
                window.addHudNotification('Finance Intelligence', message);
            }
        }
    };

    // Export globally for app.js and window
    window.FinanceDashboard = FinanceDashboard;

    // Auto-init on DOMContentLoaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => FinanceDashboard.init());
    } else {
        FinanceDashboard.init();
    }
})();
