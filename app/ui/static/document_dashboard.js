/**
 * Victor Document Intelligence & Conversational RAG Dashboard
 * 
 * Provides interactive document management, grounded semantic Q&A with exact citations,
 * deterministic Excel analytics, multi-document comparison, revision notes, and file ingestion.
 */

(function () {
    'use strict';

    let currentTab = 'library';
    let documentsData = [];
    let collectionsData = [];
    let activeDocumentId = null;

    const DocumentDashboard = {
        show: function () {
            const view = document.getElementById('documentDashboardView');
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
                b.classList.toggle('is-active', b.dataset.view === 'documents');
            });

            this.loadDocuments();
        },

        hide: function (restoreDashboard = true) {
            const view = document.getElementById('documentDashboardView');
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

        handleNavigation: function (tab, payload) {
            this.show();
            const targetTab = tab === 'study' ? 'notes' : (tab || 'library');
            this.switchTab(targetTab);

            if (payload && payload.summary) {
                const docId = payload.document_id;
                const docName = payload.file_name;
                const summaryText = payload.summary;

                const targetSelect = document.getElementById('docNotesDocSelect');
                if (targetSelect && docId) {
                    targetSelect.value = docId;
                }

                const outputEl = document.getElementById('docNotesOutput');
                if (outputEl) {
                    outputEl.innerHTML = `
                        <div class="doc-study-card">
                            <div class="doc-voice-badge">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/></svg>
                                <span>Generated via Voice Command • ${new Date().toLocaleTimeString()}</span>
                            </div>
                            <div class="doc-study-card-header">
                                <h3>Summary: ${docName || 'Document'}</h3>
                                <span class="badge-model">Voice Ingestion</span>
                            </div>
                            <div class="doc-study-body">${this.escapeAndFormatMarkdown(summaryText)}</div>
                        </div>
                    `;
                }
            }
        },

        handleUpdate: function (message) {
            if (!message) return;
            const action = message.action;
            const data = message.data || {};

            if (action === 'voice_summary') {
                this.handleNavigation('notes', {
                    document_id: data.document_id,
                    file_name: data.file_name,
                    summary: data.summary,
                });
                this.loadDocuments();
            } else if (action === 'document_ingested') {
                this.loadDocuments();
            }
        },

        switchTab: function (tabName) {
            currentTab = tabName;
            document.querySelectorAll('.doc-tab-btn').forEach(btn => {
                btn.classList.toggle('active', btn.dataset.tab === tabName);
            });
            document.querySelectorAll('.doc-tab-pane').forEach(pane => {
                pane.classList.toggle('active', pane.id === `docTab-${tabName}`);
            });

            if (tabName === 'compare') {
                this.populateCompareSelectors();
            } else if (tabName === 'excel') {
                this.populateExcelSelectors();
            }
        },

        loadDocuments: async function () {
            try {
                const res = await fetch('/api/documents');
                const data = await res.json();
                if (data.success) {
                    documentsData = data.documents || [];
                    collectionsData = data.collections || [];
                    activeDocumentId = data.active_document_id;
                    this.renderStats(data);
                    this.renderLibrary(documentsData);
                }
            } catch (err) {
                console.error('Failed to load documents:', err);
            }
        },

        renderStats: function (data) {
            const countEl = document.getElementById('docStatTotalCount');
            const chunksEl = document.getElementById('docStatTotalChunks');
            const sizeEl = document.getElementById('docStatTotalSize');
            const activeEl = document.getElementById('docStatActiveDoc');

            if (countEl) countEl.textContent = data.total_documents || 0;
            if (chunksEl) chunksEl.textContent = data.total_chunks || 0;
            if (sizeEl) sizeEl.textContent = `${data.total_size_mb || 0} MB`;

            if (activeEl) {
                const activeDoc = documentsData.find(d => d.document_id === activeDocumentId);
                activeEl.textContent = activeDoc ? activeDoc.file_name : 'None selected';
            }
        },

        renderLibrary: function (docs) {
            const tbody = document.getElementById('docLibraryTableBody');
            if (!tbody) return;

            if (!docs || docs.length === 0) {
                tbody.innerHTML = `
                    <tr>
                        <td colspan="7" class="doc-empty-row">
                            <div class="doc-empty-state">
                                <svg viewBox="0 0 24 24" width="36" height="36" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                                <p>No documents indexed yet. Upload a PDF, Word, Excel, PPTX, or text file to begin.</p>
                            </div>
                        </td>
                    </tr>
                `;
                return;
            }

            tbody.innerHTML = docs.map(doc => {
                const sizeKb = Math.round(doc.file_size_bytes / 1024);
                const pages = doc.total_pages ? `${doc.total_pages} pages` : 'N/A';
                const statusBadge = doc.status === 'INDEXED' 
                    ? '<span class="doc-badge badge-indexed">INDEXED</span>'
                    : `<span class="doc-badge badge-failed">${doc.status}</span>`;
                
                const typeClass = `type-${(doc.doc_type || 'other').toLowerCase()}`;

                return `
                    <tr data-doc-id="${doc.document_id}">
                        <td>
                            <div class="doc-file-info">
                                <span class="doc-type-icon ${typeClass}">${doc.doc_type}</span>
                                <div class="doc-file-text">
                                    <div class="doc-file-name" title="${doc.file_path}">${doc.file_name}</div>
                                    <div class="doc-file-path">${doc.file_path}</div>
                                </div>
                            </div>
                        </td>
                        <td>${doc.collection_id}</td>
                        <td>${pages}</td>
                        <td><strong>${doc.total_chunks}</strong> chunks</td>
                        <td>${sizeKb} KB</td>
                        <td>${statusBadge}</td>
                        <td>
                            <div class="doc-actions-cell">
                                <button class="doc-btn-icon" title="Query Document" onclick="DocumentDashboard.quickQuery('${doc.document_id}')">
                                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
                                </button>
                                <button class="doc-btn-icon" title="Summarize" onclick="DocumentDashboard.quickSummarize('${doc.document_id}')">
                                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><line x1="21" y1="10" x2="3" y2="10"/><line x1="21" y1="6" x2="3" y2="6"/><line x1="21" y1="14" x2="3" y2="14"/><line x1="21" y1="18" x2="7" y2="18"/></svg>
                                </button>
                                <button class="doc-btn-icon" title="Study Notes" onclick="DocumentDashboard.quickNotes('${doc.document_id}')">
                                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
                                </button>
                                <button class="doc-btn-icon btn-delete" title="Delete Document" onclick="DocumentDashboard.deleteDoc('${doc.document_id}')">
                                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                                </button>
                            </div>
                        </td>
                    </tr>
                `;
            }).join('');
        },

        deleteDoc: async function (docId) {
            const doc = documentsData.find(d => d.document_id === docId);
            const name = doc ? doc.file_name : docId;
            if (!confirm(`Delete '${name}' and remove its vector index?`)) return;

            try {
                const res = await fetch(`/api/documents/${docId}`, { method: 'DELETE' });
                const data = await res.json();
                if (data.success) {
                    this.loadDocuments();
                } else {
                    alert('Failed to delete document.');
                }
            } catch (err) {
                console.error(err);
                alert('Error deleting document: ' + err.message);
            }
        },

        // --- Ingestion Modals ---

        openUploadModal: function () {
            const modal = document.getElementById('docUploadModal');
            if (modal) modal.classList.remove('hidden');
        },

        closeUploadModal: function () {
            const modal = document.getElementById('docUploadModal');
            if (modal) modal.classList.add('hidden');
        },

        submitUpload: async function () {
            const fileInput = document.getElementById('docFileInput');
            const colInput = document.getElementById('docUploadCollectionInput');
            if (!fileInput || !fileInput.files.length) {
                alert('Please select a file to upload.');
                return;
            }

            const formData = new FormData();
            formData.append('file', fileInput.files[0]);
            formData.append('collection_id', colInput ? colInput.value : 'default');

            const btn = document.getElementById('docSubmitUploadBtn');
            if (btn) {
                btn.disabled = true;
                btn.textContent = 'Ingesting & Indexing...';
            }

            try {
                const res = await fetch('/api/documents/upload', {
                    method: 'POST',
                    body: formData,
                });
                const data = await res.json();
                if (data.success) {
                    this.closeUploadModal();
                    fileInput.value = '';
                    this.loadDocuments();
                } else {
                    alert('Ingestion error: ' + (data.error || 'Unknown error'));
                }
            } catch (err) {
                alert('Upload failed: ' + err.message);
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = 'Upload & Ingest';
                }
            }
        },

        openPathModal: function () {
            const modal = document.getElementById('docPathModal');
            if (modal) modal.classList.remove('hidden');
        },

        closePathModal: function () {
            const modal = document.getElementById('docPathModal');
            if (modal) modal.classList.add('hidden');
        },

        submitPathIngest: async function () {
            const pathInput = document.getElementById('docPathInput');
            const colInput = document.getElementById('docPathCollectionInput');
            if (!pathInput || !pathInput.value.trim()) {
                alert('Please enter a valid file path.');
                return;
            }

            const btn = document.getElementById('docSubmitPathBtn');
            if (btn) {
                btn.disabled = true;
                btn.textContent = 'Indexing...';
            }

            try {
                const res = await fetch('/api/documents/ingest', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        file_path: pathInput.value.trim(),
                        collection_id: colInput ? colInput.value : 'default',
                        force_reindex: false,
                    }),
                });
                const data = await res.json();
                if (data.success) {
                    this.closePathModal();
                    pathInput.value = '';
                    this.loadDocuments();
                } else {
                    alert('Ingestion error: ' + (data.error || 'Unknown error'));
                }
            } catch (err) {
                alert('Ingestion failed: ' + err.message);
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = 'Index Document';
                }
            }
        },

        // --- Conversational Q&A & Search ---

        sendQuery: async function () {
            const input = document.getElementById('docQueryInput');
            if (!input || !input.value.trim()) return;

            const q = input.value.trim();
            const resultsBox = document.getElementById('docQueryResults');
            if (!resultsBox) return;

            // Render user question
            const qEl = document.createElement('div');
            qEl.className = 'doc-chat-bubble doc-chat-user';
            qEl.textContent = q;
            resultsBox.appendChild(qEl);

            // Placeholder answer
            const aEl = document.createElement('div');
            aEl.className = 'doc-chat-bubble doc-chat-ai doc-chat-loading';
            aEl.innerHTML = '<span class="doc-spinner"></span> Victor is analyzing document index...';
            resultsBox.appendChild(aEl);
            resultsBox.scrollTop = resultsBox.scrollHeight;

            input.value = '';

            try {
                const res = await fetch('/api/documents/query', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        query: q,
                        collection_id: 'default',
                        top_k: 5,
                    }),
                });
                const data = await res.json();
                if (data.success && data.response) {
                    const r = data.response;
                    const citationsHtml = (r.citations && r.citations.length > 0)
                        ? `
                            <div class="doc-citations-block">
                                <div class="doc-citations-title">Sources Cited:</div>
                                <div class="doc-citations-list">
                                    ${r.citations.map(c => `
                                        <div class="doc-citation-chip" title="${c.snippet}">
                                            <span class="cit-name">${c.document_name}</span>
                                            ${c.page_number ? `<span class="cit-loc">Pg ${c.page_number}</span>` : ''}
                                            ${c.section_title ? `<span class="cit-sec">${c.section_title}</span>` : ''}
                                            ${c.sheet_name ? `<span class="cit-sheet">${c.sheet_name}</span>` : ''}
                                            ${c.slide_number ? `<span class="cit-slide">Slide ${c.slide_number}</span>` : ''}
                                            <span class="cit-score">${Math.round(c.confidence_score * 100)}%</span>
                                        </div>
                                    `).join('')}
                                </div>
                            </div>
                        ` : '';

                    aEl.className = 'doc-chat-bubble doc-chat-ai';
                    aEl.innerHTML = `
                        <div class="doc-chat-meta">
                            <span class="meta-provider">${r.provider_used || 'Victor RAG'}</span>
                            <span class="meta-model">${r.model_used || ''}</span>
                            <span class="meta-lat">${Math.round(r.latency_ms)}ms</span>
                        </div>
                        <div class="doc-chat-text">${this.escapeAndFormatMarkdown(r.answer)}</div>
                        ${citationsHtml}
                    `;
                } else {
                    aEl.className = 'doc-chat-bubble doc-chat-ai';
                    aEl.textContent = 'Could not generate answer.';
                }
            } catch (err) {
                aEl.className = 'doc-chat-bubble doc-chat-ai';
                aEl.textContent = 'Query failed: ' + err.message;
            }
            resultsBox.scrollTop = resultsBox.scrollHeight;
        },

        quickQuery: function (docId) {
            this.switchTab('qa');
            activeDocumentId = docId;
            const input = document.getElementById('docQueryInput');
            if (input) {
                const doc = documentsData.find(d => d.document_id === docId);
                const name = doc ? doc.file_name : '';
                input.placeholder = `Ask a question about ${name}...`;
                input.focus();
            }
        },

        // --- Summaries & Notes ---

        quickSummarize: async function (docId) {
            this.switchTab('notes');
            const targetSelect = document.getElementById('docNotesDocSelect');
            if (targetSelect) targetSelect.value = docId;
            this.generateSummary(docId);
        },

        quickNotes: async function (docId) {
            this.switchTab('notes');
            const targetSelect = document.getElementById('docNotesDocSelect');
            if (targetSelect) targetSelect.value = docId;
            this.generateRevisionNotes(docId);
        },

        generateSummary: async function (docId) {
            const id = docId || document.getElementById('docNotesDocSelect')?.value;
            if (!id) {
                alert('Please select a document.');
                return;
            }

            const outputEl = document.getElementById('docNotesOutput');
            if (outputEl) {
                outputEl.innerHTML = '<div class="doc-loading-pane"><span class="doc-spinner"></span> Generating comprehensive document summary...</div>';
            }

            try {
                const res = await fetch('/api/documents/summarize', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ document_id: id, summary_type: 'comprehensive' }),
                });
                const data = await res.json();
                if (data.success && outputEl) {
                    outputEl.innerHTML = `
                        <div class="doc-study-card">
                            <div class="doc-study-card-header">
                                <h3>Executive Document Summary</h3>
                                <span class="badge-model">${data.response.model_used || ''}</span>
                            </div>
                            <div class="doc-study-body">${this.escapeAndFormatMarkdown(data.response.answer)}</div>
                        </div>
                    `;
                }
            } catch (err) {
                if (outputEl) outputEl.innerHTML = `<div class="doc-error-pane">Summary failed: ${err.message}</div>`;
            }
        },

        generateRevisionNotes: async function (docId) {
            const id = docId || document.getElementById('docNotesDocSelect')?.value;
            if (!id) {
                alert('Please select a document.');
                return;
            }

            const outputEl = document.getElementById('docNotesOutput');
            if (outputEl) {
                outputEl.innerHTML = '<div class="doc-loading-pane"><span class="doc-spinner"></span> Extracting key definitions, concepts, and revision notes...</div>';
            }

            try {
                const res = await fetch('/api/documents/notes', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ document_id: id }),
                });
                const data = await res.json();
                if (data.success && outputEl) {
                    outputEl.innerHTML = `
                        <div class="doc-study-card">
                            <div class="doc-study-card-header">
                                <h3>Key Concepts & Revision Notes</h3>
                                <span class="badge-model">${data.response.model_used || ''}</span>
                            </div>
                            <div class="doc-study-body">${this.escapeAndFormatMarkdown(data.response.answer)}</div>
                        </div>
                    `;
                }
            } catch (err) {
                if (outputEl) outputEl.innerHTML = `<div class="doc-error-pane">Notes generation failed: ${err.message}</div>`;
            }
        },

        // --- Multi-Document Comparison ---

        populateCompareSelectors: function () {
            const s1 = document.getElementById('docCompareDoc1');
            const s2 = document.getElementById('docCompareDoc2');
            if (!s1 || !s2) return;

            const options = documentsData.map(d => `<option value="${d.document_id}">${d.file_name} (${d.doc_type})</option>`).join('');
            s1.innerHTML = '<option value="">Select Document 1</option>' + options;
            s2.innerHTML = '<option value="">Select Document 2</option>' + options;

            if (documentsData.length >= 2) {
                s1.selectedIndex = 1;
                s2.selectedIndex = 2;
            }
        },

        submitCompare: async function () {
            const d1 = document.getElementById('docCompareDoc1')?.value;
            const d2 = document.getElementById('docCompareDoc2')?.value;
            if (!d1 || !d2) {
                alert('Please select two different documents to compare.');
                return;
            }
            if (d1 === d2) {
                alert('Please select two different documents.');
                return;
            }

            const outputEl = document.getElementById('docCompareOutput');
            if (outputEl) {
                outputEl.innerHTML = '<div class="doc-loading-pane"><span class="doc-spinner"></span> Performing comparative analysis between documents...</div>';
            }

            try {
                const res = await fetch('/api/documents/compare', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ document_id_1: d1, document_id_2: d2 }),
                });
                const data = await res.json();
                if (data.success && outputEl) {
                    outputEl.innerHTML = `
                        <div class="doc-study-card">
                            <div class="doc-study-card-header">
                                <h3>Comparative Analysis</h3>
                                <span class="badge-model">${data.response.model_used || ''}</span>
                            </div>
                            <div class="doc-study-body">${this.escapeAndFormatMarkdown(data.response.answer)}</div>
                        </div>
                    `;
                }
            } catch (err) {
                if (outputEl) outputEl.innerHTML = `<div class="doc-error-pane">Comparison failed: ${err.message}</div>`;
            }
        },

        // --- Excel Deterministic Analytics ---

        populateExcelSelectors: function () {
            const select = document.getElementById('docExcelDocSelect');
            if (!select) return;

            const excelDocs = documentsData.filter(d => ['XLSX', 'XLS', 'CSV'].includes(d.doc_type));
            if (!excelDocs.length) {
                select.innerHTML = '<option value="">No Excel or CSV files indexed</option>';
                return;
            }
            select.innerHTML = excelDocs.map(d => `<option value="${d.file_path}">${d.file_name}</option>`).join('');
        },

        calculateExcelQuery: async function () {
            const select = document.getElementById('docExcelDocSelect');
            const qInput = document.getElementById('docExcelQueryInput');
            const outputEl = document.getElementById('docExcelOutput');
            if (!select || !select.value || !qInput || !qInput.value.trim()) {
                alert('Please select an Excel/CSV file and enter a calculation query.');
                return;
            }

            const filePath = select.value;
            const query = qInput.value.trim();

            if (outputEl) {
                outputEl.innerHTML = '<div class="doc-loading-pane"><span class="doc-spinner"></span> Executing deterministic pandas calculation...</div>';
            }

            try {
                const res = await fetch('/api/documents/query', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query: `${query} in ${filePath}` }),
                });
                const data = await res.json();
                if (data.success && outputEl) {
                    outputEl.innerHTML = `
                        <div class="doc-study-card">
                            <div class="doc-study-card-header">
                                <h3>Calculation Result (Deterministic)</h3>
                                <span class="badge-model">pandas / ExcelIntelligenceEngine</span>
                            </div>
                            <div class="doc-study-body">${this.escapeAndFormatMarkdown(data.response.answer)}</div>
                        </div>
                    `;
                }
            } catch (err) {
                if (outputEl) outputEl.innerHTML = `<div class="doc-error-pane">Calculation failed: ${err.message}</div>`;
            }
        },

        escapeAndFormatMarkdown: function (text) {
            if (!text) return '';
            // Basic formatting for headers, bold, bullet points, and code
            let formatted = text
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                .replace(/\*(.*?)\*/g, '<em>$1</em>')
                .replace(/`([^`]+)`/g, '<code>$1</code>')
                .replace(/^### (.*$)/gim, '<h4>$1</h4>')
                .replace(/^## (.*$)/gim, '<h3>$1</h3>')
                .replace(/^# (.*$)/gim, '<h2>$1</h2>')
                .replace(/^\- (.*$)/gim, '<li>$1</li>')
                .replace(/\n\n/g, '<br><br>')
                .replace(/\n/g, '<br>');

            return formatted;
        },
    };

    window.DocumentDashboard = DocumentDashboard;

    // Attach listeners on DOMContentLoaded
    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('.doc-tab-btn').forEach(btn => {
            btn.addEventListener('click', () => DocumentDashboard.switchTab(btn.dataset.tab));
        });

        const queryInput = document.getElementById('docQueryInput');
        if (queryInput) {
            queryInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') DocumentDashboard.sendQuery();
            });
        }

        const closeBtn = document.getElementById('docCloseBtn');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                if (typeof window.openModuleView === 'function') {
                    window.openModuleView('dashboard');
                } else {
                    DocumentDashboard.hide(true);
                }
            });
        }

        // Close modal when clicking on overlay background backdrop
        document.querySelectorAll('.doc-modal-overlay').forEach(overlay => {
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) overlay.classList.add('hidden');
            });
        });
    });

})();
