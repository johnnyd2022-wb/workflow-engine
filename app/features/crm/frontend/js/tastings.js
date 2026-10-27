(function () {
    'use strict';
    var ROOT = '[data-tastings-root]';
    var TZ = 'Pacific/Auckland';
    var STATES = { planned: 'Planned', dispatched: 'Stock out', completed: 'Completed', cancelled: 'Cancelled' };
    function el(tag, cls, text) {
        var node = document.createElement(tag);
        if (cls) node.className = cls;
        if (text != null) node.textContent = String(text);
        return node;
    }
    function parts(value) {
        var result = {};
        new Intl.DateTimeFormat('en-NZ', { timeZone: TZ, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).formatToParts(new Date(value)).forEach(function (p) { result[p.type] = p.value; });
        return result;
    }
    function nzDay(value) { var p = parts(value); return p.year + '-' + p.month + '-' + p.day; }
    function wall(value) { var p = parts(value); return p.year + '-' + p.month + '-' + p.day + 'T' + p.hour + ':' + p.minute; }
    function dateLabel(day, options) { return new Intl.DateTimeFormat('en-NZ', Object.assign({ timeZone: TZ, day: 'numeric', month: 'short' }, options || {})).format(new Date(day + 'T00:00:00Z')); }
    function timeLabel(value) { return new Intl.DateTimeFormat('en-NZ', { timeZone: TZ, hour: 'numeric', minute: '2-digit' }).format(new Date(value)); }
    function nzISO(raw) {
        if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(raw)) throw new Error('Choose a start and end time.');
        var guess = Date.parse(raw + ':00Z');
        var localAtGuess = Date.parse(wall(guess) + ':00Z');
        var instant = guess - (localAtGuess - guess);
        if (wall(instant) !== raw || wall(instant - 3600000) === raw || wall(instant + 3600000) === raw) {
            throw new Error('That NZ time is in the daylight-saving clock-change hour. Choose an unambiguous time.');
        }
        var offset = Math.round((guess - instant) / 60000);
        return raw + ':00' + (offset < 0 ? '-' : '+') + String(Math.floor(Math.abs(offset) / 60)).padStart(2, '0') + ':' + String(Math.abs(offset) % 60).padStart(2, '0');
    }
    function amount(value) { return new Intl.NumberFormat('en-NZ', { maximumFractionDigits: 4 }).format(Number(value || 0)); }
    function statusOf(event) { return event.status || event.state || 'planned'; }
    function dutyLabel(lot) {
        var basis = lot.basis || {};
        var status = String(lot.duty_status || basis.status || '');
        return /unresolved|missing|review/.test(status) || basis.problems && basis.problems.length ? 'Excise needs review' : 'Removal recorded';
    }
    function init() {
        var root = document.querySelector(ROOT);
        if (!root || root._tastingsAbort) return;
        var $ = function (selector) { return root.querySelector(selector); };
        var canRecord = root.dataset.canRecord === 'true';
        var canDispatch = root.dataset.canDispatch === 'true';
        var controller = new AbortController();
        root._tastingsAbort = function () { controller.abort(); delete root._tastingsAbort; };
        var state = { pool: [], choices: { reps: [], contacts: [], stock: [] }, lines: [], editing: null, detail: null, poolOffset: 0, choiceOffset: 0, peopleOffset: 0, choiceToken: 0, peopleToken: 0, loadToken: 0, busy: false, draft: null };
        var editor = $('#tasting-editor');
        var detail = $('#tasting-detail');
        var form = $('#tasting-form');
        var stockDialog = $("#tasting-stock");
        editor.close(); detail.close(); stockDialog.close();
        function error(node, message) { node.textContent = message; node.hidden = !message; }
        function notice(message) { error($('[data-tasting-status]'), message); }
        async function api(path, options) {
            options = options || {};
            var headers = Object.assign({ Accept: 'application/json' }, options.headers || {});
            if (options.method && options.method !== 'GET') {
                headers['Content-Type'] = 'application/json';
                var csrf = document.querySelector('meta[name="csrf-token"]');
                if (csrf) headers['X-CSRFToken'] = csrf.content;
            }
            var response = await fetch((options.taskCreate ? '/api/crm/tasks' : '/api/crm/tastings' + path), Object.assign({}, options, { headers: headers, credentials: 'same-origin', signal: controller.signal }));
            var body = await response.json().catch(function () { return {}; });
            if (!response.ok) throw new Error(typeof body.error === 'string' ? body.error : 'The tasting could not be loaded. Try again.');
            return body;
        }
        function option(select, value, label) { var o = el('option', '', label); o.value = value; select.appendChild(o); }
        function selectedChoices(select, choices, value, placeholder) {
            select.replaceChildren(); option(select, '', placeholder);
            choices.forEach(function (choice) { option(select, choice.id, choice.name || choice.display_name || choice.email); });
            if (value && !choices.some(function (choice) { return choice.id === value; })) option(select, value, 'Previously selected person');
            select.value = value || '';
        }
        function renderPool() {
            var host = $('[data-tasting-pool]'); host.replaceChildren();
            $('[data-tasting-pool-empty]').hidden = state.pool.length > 0;
            state.pool.forEach(function (lot) {
                var row = el('article', 'tasting-pool-lot'); row.dataset.tastingLotId = lot.id; row.append(el('h3', '', lot.product));
                row.append(el('p', '', (lot.batch ? 'Batch ' + lot.batch + ' · ' : '') + dutyLabel(lot)));
                var available = el('p'); available.append(el('strong', '', amount(lot.available_volume_ml) + ' mL'), document.createTextNode(' available')); row.append(available);
                if (Number(lot.reserved_volume_ml) > 0) row.append(el('p', '', amount(lot.reserved_volume_ml) + ' mL assigned to a tasting'));
                if (canRecord && Number(lot.available_volume_ml) > 0) { var reuse = el('button', 'tasting-text-button', 'Use at a tasting'); reuse.type = 'button'; reuse.addEventListener('click', function () { stockDialog.close(); state.draft = null; openEditor(null, lot); }); row.append(reuse); }
                host.append(row);
            });
            $('[data-tasting-pool-more]').hidden = !state.poolMore;
        }
        async function loadPool(more) {
            var token = ++state.loadToken;
            error($('[data-tasting-pool-error]'), ''); $('[data-tasting-pool-retry]').hidden = true;
            $('[data-tasting-pool-loading]').hidden = false; $('[data-tasting-pool-more]').disabled = true;
            var offset = more ? state.poolOffset + 50 : 0;
            try {
                var result = await api('/pool' + (offset ? '?offset=' + offset : ''));
                if (!root.isConnected || token !== state.loadToken) return;
                state.pool = more ? state.pool.concat(result.lots || []) : result.lots || []; state.poolOffset = offset; state.poolMore = !!result.has_more; renderPool();
            } catch (err) {
                if (err.name === 'AbortError') return;
                state.poolRetryMore = !!more; error($('[data-tasting-pool-error]'), err.message); $('[data-tasting-pool-retry]').hidden = false;
                throw err;
            } finally { if (token === state.loadToken) { $('[data-tasting-pool-loading]').hidden = true; $('[data-tasting-pool-more]').disabled = false; } }
        }
        async function load() {
            root.dispatchEvent(new CustomEvent('tasting-changed', { bubbles: true }));
            // Accounting writes must remain visibly successful if a subsequent pool refresh fails.
            if (stockDialog.open) await loadPool().catch(function () {});
        }
        function captureDraft() {
            state.draft = { fields: {}, lines: state.lines.map(function (line) { return Object.assign({}, line); }) };
            Array.from(form.elements).forEach(function (field) { if (field.name) state.draft.fields[field.name] = field.value; });
        }
        function renderLines() {
            var host = $('[data-tasting-lines]'); host.replaceChildren();
            state.lines.forEach(function (line, index) {
                var row = el('div', 'tasting-stock-line');
                var sourceLabel = el('label', '', 'Product and batch'); var select = el('select'); select.required = true; select.setAttribute('aria-label', 'Product and batch ' + (index + 1));
                option(select, '', 'Choose stock');
                state.choices.stock.forEach(function (item) { option(select, 'stock:' + item.id, item.name + (item.batch ? ' · ' + item.batch : '') + ' · ' + amount(item.quantity) + ' ' + item.unit + ' on hand'); });
                state.pool.forEach(function (lot) { if (Number(lot.available_volume_ml) > 0 || lot.id === line.source_pool_id) option(select, 'pool:' + lot.id, lot.product + (lot.batch ? ' · ' + lot.batch : '') + ' · tasting stock (' + amount(lot.available_volume_ml) + ' mL available)'); });
                var chosen = line.source_pool_id ? 'pool:' + line.source_pool_id : line.source_item_id ? 'stock:' + line.source_item_id : '';
                if (chosen && !Array.from(select.options).some(function (o) { return o.value === chosen; })) option(select, chosen, (line.product || 'Selected stock') + (line.batch ? ' · ' + line.batch : ''));
                select.value = chosen;
                select.addEventListener('change', function () {
                    var pair = select.value.split(':');
                    delete line.source_item_id; delete line.source_pool_id;
                    delete line.product; delete line.batch; delete line.unit;
                    if (pair[0] === 'pool') line.source_pool_id = pair[1];
                    else if (pair[1]) {
                        line.source_item_id = pair[1];
                        var selected = state.choices.stock.find(function (item) { return item.id === pair[1]; });
                        // Keep selected display metadata when the next stock search replaces its results.
                        if (selected) { line.product = selected.name; line.batch = selected.batch; line.unit = selected.unit; }
                    }
                    line.quantity = pair[0] === 'pool' ? '100' : '1'; renderLines();
                });
                sourceLabel.append(select);
                var unit = line.source_pool_id ? 'mL' : (state.choices.stock.find(function (s) { return s.id === line.source_item_id; }) || line).unit || 'units';
                var quantityLabel = el('label', '', 'Quantity · ' + unit); var quantity = el('input'); quantity.type = 'number'; quantity.min = '0.0001'; quantity.step = /bottle|can|keg|unit|each|pack/i.test(unit) ? '1' : '0.0001'; quantity.min = quantity.step === '1' ? '1' : '0.0001'; quantity.required = true; quantity.value = line.quantity || '1'; quantity.setAttribute('aria-label', 'Quantity ' + (index + 1)); quantity.addEventListener('input', function () { line.quantity = quantity.value; }); quantityLabel.append(quantity);
                var remove = el('button', 'tasting-close', '×'); remove.type = 'button'; remove.setAttribute('aria-label', 'Remove stock line ' + (index + 1)); remove.addEventListener('click', function () { state.lines.splice(index, 1); renderLines(); });
                row.append(sourceLabel, quantityLabel, remove); host.append(row);
            });
        }
        async function choices(more) {
            var q = $('#tasting-stock-search').value.trim(); var offset = more ? state.choiceOffset + 50 : 0;
            var token = ++state.choiceToken;
            var body = await api('/choices?q=' + encodeURIComponent(q) + '&offset=' + offset);
            if (token !== state.choiceToken) return;
            state.choices.stock = more ? state.choices.stock.concat(body.stock || []) : body.stock || []; state.choiceOffset = offset;
            $('[data-tasting-stock-more]').hidden = !body.has_more;
            renderLines();
        }
        async function people(more) {
            var offset = more ? state.peopleOffset + 50 : 0;
            var token = ++state.peopleToken;
            var body = await api('/choices?people_q=' + encodeURIComponent($('#tasting-people-search').value.trim()) + '&people_offset=' + offset);
            if (token !== state.peopleToken) return;
            state.choices.reps = more ? state.choices.reps.concat(body.reps || []) : body.reps || [];
            state.choices.contacts = more ? state.choices.contacts.concat(body.contacts || []) : body.contacts || [];
            state.peopleOffset = offset; $('[data-tasting-people-more]').hidden = !body.people_has_more;
            selectedChoices(form.elements.rep_id, state.choices.reps, form.elements.rep_id.value, 'Choose a rep');
            selectedChoices(form.elements.contact_id, state.choices.contacts, form.elements.contact_id.value, 'No linked customer');
        }
        async function openEditor(event, pool, seed) {
            if (!canRecord) return;
            state.editing = event ? event.id : null; form.reset(); error($('[data-tasting-form-error]'), ''); $('#tasting-stock-search').value = ''; $('#tasting-people-search').value = '';
            state.lines = event ? (event.allocations || []).map(function (line) { return Object.assign({}, line); }) : pool ? [{ source_pool_id: pool.id, quantity: String(Math.min(100, Number(pool.available_volume_ml))) }] : [];
            $('#tasting-editor-title').textContent = event ? 'Edit tasting task' : 'New tasting task';
            $('#tasting-task-type').value = 'tasting'; $('#tasting-task-type').disabled = !!event;
            ['title', 'venue_name', 'venue_address', 'venue_type', 'licence_reference', 'notes'].forEach(function (key) { form.elements[key].value = event && event[key] || (key === 'venue_type' ? 'external' : ''); });
            var day = nzDay(Date.now()); form.elements.starts.value = event ? wall(event.starts_at) : day + 'T17:00'; form.elements.ends.value = event ? wall(event.ends_at) : day + 'T19:00';
            selectedChoices(form.elements.rep_id, state.choices.reps, event && event.rep_id, 'Choose a rep'); selectedChoices(form.elements.contact_id, state.choices.contacts, event && event.contact_id, 'No linked customer');
            if (!event && !pool && state.draft) {
                Object.keys(state.draft.fields).forEach(function (key) { form.elements[key].value = state.draft.fields[key]; });
                state.lines = state.draft.lines.map(function (line) { return Object.assign({}, line); });
            }
            if (seed) {
                form.elements.title.value = seed.title || ''; form.elements.notes.value = seed.description || '';
                selectedChoices(form.elements.rep_id, state.choices.reps, seed.assigned_to_user_id, 'Choose a rep');
                selectedChoices(form.elements.contact_id, state.choices.contacts, seed.contact_id, 'No linked customer');
                if (seed.due_date && seed.due_date !== form.elements.starts.value.slice(0, 10)) {
                    var delta = (Date.parse(seed.due_date) - Date.parse(form.elements.starts.value.slice(0, 10))) / 86400000;
                    ['starts', 'ends'].forEach(function (key) {
                        var field = form.elements[key]; var date = new Date(field.value.slice(0, 10) + 'T12:00:00Z');
                        date.setUTCDate(date.getUTCDate() + delta); field.value = date.toISOString().slice(0, 10) + field.value.slice(10);
                    });
                }
            }
            if (detail.open) detail.close(); renderLines(); editor.showModal();
            try { await Promise.all([choices(false), people(false), loadPool()]); renderLines(); if (event) { form.elements.rep_id.value = event.rep_id || ''; form.elements.contact_id.value = event.contact_id || ''; } }
            catch (err) { if (err.name !== 'AbortError') error($('[data-tasting-form-error]'), err.message); }
        }
        function fact(label, value) { var node = el('div', 'tasting-detail-fact'); node.append(el('span', '', label), el('span', '', value || 'Not recorded')); return node; }
        async function mutate(path, body, target, headers) {
            if (state.busy) return null;
            state.busy = true; error(target, ''); root.querySelectorAll('dialog button').forEach(function (b) { b.disabled = true; });
            try { return await api(path, { method: 'POST', body: JSON.stringify(body), headers: headers || {} }); }
            catch (err) { if (err.name !== 'AbortError') error(target, err.message); return null; }
            finally { state.busy = false; root.querySelectorAll('dialog button').forEach(function (b) { b.disabled = false; }); }
        }
        function showDetail(event) {
            if (!root.isConnected) return;
            state.detail = event; var body = $('[data-tasting-detail-body]'); body.replaceChildren(); error($('[data-tasting-detail-error]'), ''); $('#tasting-detail-title').textContent = event.title;
            var facts = el('div', 'tasting-detail-facts');
            facts.append(fact('When · NZ time', dateLabel(nzDay(event.starts_at), { weekday: 'long', year: 'numeric' }) + ' · ' + timeLabel(event.starts_at) + ' – ' + (nzDay(event.starts_at) !== nzDay(event.ends_at) ? dateLabel(nzDay(event.ends_at), { weekday: 'short' }) + ' · ' : '') + timeLabel(event.ends_at)), fact('Rep', event.rep_name), fact(event.venue_type === 'own' ? 'Our venue' : 'External venue', event.venue_name), fact('Address', event.venue_address), fact('Venue licence reference', event.licence_reference), fact('Status', STATES[statusOf(event)])); body.append(facts);
            if (event.notes) body.append(el('p', 'tasting-detail-note', event.notes));
            if (event.outcome_notes) { body.append(el('h3', 'tasting-section-title', 'Outcome notes'), el('p', 'tasting-detail-note', event.outcome_notes)); }
            if (event.samples_count != null) body.append(el('p', 'tasting-detail-note', amount(event.samples_count) + ' samples served'));
            var stock = el('section', 'tasting-detail-section'); stock.append(el('h3', '', 'Stock and outcome'));
            var lines = event.allocations || []; var usageInputs = [];
            if (!lines.length) stock.append(el('p', 'workspace-caption', 'No stock planned yet. Add the batches the rep will take.'));
            lines.forEach(function (line) {
                var row = el('div', 'tasting-detail-line'); row.append(el('strong', '', line.product || 'Selected stock'));
                row.append(el('p', '', [line.batch ? 'Batch ' + line.batch : null, amount(line.quantity) + ' ' + (line.source_pool_id ? 'mL from tasting stock' : line.unit || 'units')].filter(Boolean).join(' · ')));
                if (statusOf(event) === 'dispatched' && canRecord) {
                    var label = el('label', '', 'Sampled · mL (of ' + amount(line.reserved_volume_ml) + ')'); var used = el('input'); used.type = 'number'; used.min = '0'; used.max = line.reserved_volume_ml; used.step = '0.0001'; used.value = '0'; used.required = true; used.setAttribute('aria-label', 'Sampled mL · ' + (line.product || 'stock')); label.append(used); row.append(label); usageInputs.push({ id: line.id, input: used });
                } else if (statusOf(event) === 'dispatched') row.append(el('p', '', amount(line.reserved_volume_ml) + ' mL assigned'));
                else if (line.used_volume_ml != null && statusOf(event) === 'completed') row.append(el('p', '', amount(line.used_volume_ml) + ' mL sampled'));
                var poolLot = line.basis ? {basis: line.basis, duty_status: line.duty_status} : state.pool.find(function (lot) { return lot.id === line.stock_lot_id; });
                if (poolLot) {
                    row.append(el('p', '', dutyLabel(poolLot)));
                    var proof = el('details'); proof.append(el('summary', '', 'Removal evidence'));
                    var basis = poolLot.basis || {};
                    var labels = {occurred_on:'Removal date', product:'Product', tariff_item:'Excise item', abv_percent:'Alcohol strength (%)', litres:'Litres', lal:'Litres of alcohol', duty:'Recorded excise duty ($)', rate_date:'Rate effective', source_location:'Stock source'};
                    Object.keys(labels).forEach(function (key) { if (basis[key] != null) proof.append(el('p', '', labels[key] + ': ' + basis[key])); });
                    if (basis.source_cca) proof.append(el('p', '', 'Source CCA: ' + (basis.source_cca.number || basis.source_cca.name)));
                    (basis.problems || []).forEach(function (problem) { proof.append(el('p', '', problem)); });
                    row.append(proof);
                }
                stock.append(row);
            }); body.append(stock);
            var actions = el('footer', 'tasting-dialog-actions');
            if (statusOf(event) === 'planned' && canRecord) { var edit = el('button', 'workspace-button', 'Edit plan'); edit.type = 'button'; edit.addEventListener('click', function () { openEditor(event); }); actions.append(edit); }
            if (statusOf(event) === 'planned' && canDispatch && lines.length) {
                var dispatchForm = el('form', 'tasting-detail-section'); dispatchForm.append(el('h3', '', event.venue_type === 'own' ? 'Record stock used at our venue' : 'Confirm stock has left'));
                dispatchForm.append(el('p', 'workspace-caption', 'Use the actual removal date. This debits warehouse stock and records the removal for excise. It does not lodge or pay a return.'));
                var date = el('input'); date.type = 'date'; date.required = true; date.value = nzDay(Date.now()); date.max = nzDay(Date.now()); var label = el('label', '', 'Actual removal date'); label.append(date); dispatchForm.append(label);
                var send = el('button', 'workspace-button workspace-button--primary', 'Confirm stock removal'); send.type = 'submit'; var sendActions = el('div', 'tasting-dialog-actions'); sendActions.append(send); dispatchForm.append(sendActions);
                var dispatchKey = crypto.randomUUID();
                dispatchForm.addEventListener('submit', async function (e) { e.preventDefault(); var result = await mutate('/' + event.id + '/dispatch', { actual_date: date.value }, $('[data-tasting-detail-error]'), { 'Idempotency-Key': dispatchKey }); if (result) { await load(true); showDetail(result.tasting); notice('Stock removal recorded. Add the tasting outcome when the rep returns.'); } }); body.append(dispatchForm);
            } else if (statusOf(event) === 'planned' && !canDispatch && canRecord && lines.length) body.append(el('p', 'workspace-caption', 'A stock manager can confirm the physical stock removal.'));
            if (statusOf(event) === 'dispatched' && canRecord) {
                var outcome = el('form', 'tasting-detail-section'); outcome.append(el('h3', '', 'Record the outcome'), el('p', 'workspace-caption', 'Enter measured mL sampled against each batch above. Unsampled stock stays in tasting stock for the next visit.'));
                var fields = el('div', 'tasting-fields'); var sampleLabel = el('label', '', 'Samples served · optional'); var samples = el('input'); samples.type = 'number'; samples.min = '0'; samples.max = '1000000'; samples.step = '1'; sampleLabel.append(samples); fields.append(sampleLabel); outcome.append(fields);
                var noteLabel = el('label', '', 'Outcome notes · optional'); var notes = el('textarea'); notes.rows = 3; notes.maxLength = 4000; noteLabel.append(notes); outcome.append(noteLabel);
                var finish = el('button', 'workspace-button workspace-button--primary', 'Complete tasting'); finish.type = 'submit'; var endActions = el('div', 'tasting-dialog-actions'); endActions.append(finish); outcome.append(endActions);
                outcome.addEventListener('submit', async function (e) { e.preventDefault(); var usage = []; for (var item of usageInputs) { if (!item.input.reportValidity()) return; usage.push({ allocation_id: item.id, used_volume_ml: item.input.value }); } var result = await mutate('/' + event.id + '/finalise', { usage: usage, samples_count: samples.value === '' ? null : Number(samples.value), notes: notes.value }, $('[data-tasting-detail-error]')); if (result) { await load(true); showDetail(result.tasting); notice('Tasting completed. Unsampled stock is available for the next tasting.'); } }); body.append(outcome);
            }
            if (canRecord && ['planned', 'dispatched'].includes(statusOf(event))) {
                var cancel = el('button', 'tasting-text-button', 'Cancel tasting'); cancel.type = 'button'; cancel.addEventListener('click', async function () { if (!window.confirm(statusOf(event) === 'dispatched' ? 'Cancel this tasting? Dispatched stock stays in tasting stock and its removal for excise remains recorded.' : 'Cancel this tasting? No stock will be removed.')) return; var result = await mutate('/' + event.id + '/cancel', {}, $('[data-tasting-detail-error]')); if (result) { await load(true); showDetail(result.tasting); notice('Tasting cancelled. Its history has been retained.'); } }); actions.append(cancel);
            }
            if (actions.childElementCount) body.append(actions); if (!detail.open) detail.showModal();
        }
        async function openDetail(id) { try { var result = await api('/' + encodeURIComponent(id)); if (root.isConnected) showDetail(result.tasting); } catch (err) { if (err.name !== 'AbortError') notice(err.message); } }
        form.addEventListener('submit', async function (e) {
            e.preventDefault(); if (state.busy) return;
            var target = $('[data-tasting-form-error]'); error(target, '');
            if (form.elements.title.value.length > 160 || form.elements.notes.value.length > 4000) { error(target, 'Keep the tasting name within 160 characters and notes within 4,000 characters. Your draft has been retained.'); return; }
            try {
                var data = {}; ['title', 'venue_name', 'venue_address', 'venue_type', 'licence_reference', 'notes', 'rep_id'].forEach(function (key) { data[key] = form.elements[key].value; });
                data.contact_id = form.elements.contact_id.value || null; data.starts_at = nzISO(form.elements.starts.value); data.ends_at = nzISO(form.elements.ends.value);
                data.allocations = state.lines.map(function (line) { var result = { quantity: line.quantity }; if (line.source_pool_id) result.source_pool_id = line.source_pool_id; else result.source_item_id = line.source_item_id; return result; });
                state.busy = true; $('[data-tasting-save]').disabled = true;
                var result = state.editing ? await api('/' + state.editing, { method: 'PUT', body: JSON.stringify(data) }) : await api('', { method: 'POST', body: JSON.stringify({ task_type: 'tasting', tasting: data }), taskCreate: true });
                state.draft = null; editor.close(); await load(true); showDetail(result.tasting); notice('Tasting saved to the shared Sales and Production calendar.');
            } catch (err) { if (err.name !== 'AbortError') error(target, err.message); }
            finally { state.busy = false; $('[data-tasting-save]').disabled = false; }
        });
        root.querySelectorAll('[data-tasting-new]').forEach(function (button) { button.addEventListener('click', function () { openEditor(null); }); });
        root.querySelectorAll('[data-tasting-close]').forEach(function (button) { button.addEventListener('click', function () { button.closest('dialog').close(); }); });
        $('[data-tasting-add-line]').addEventListener('click', function () { if (state.lines.length >= 20) return; state.lines.push({ quantity: '1' }); renderLines(); });
        ['people', 'stock'].forEach(function (kind) { $('#tasting-' + kind + '-search').addEventListener('keydown', function (event) { if (event.key === 'Enter') { event.preventDefault(); $('[data-tasting-find-' + kind + ']').click(); } }); });
        $('[data-tasting-find-people]').addEventListener('click', function () { people(false).catch(function (err) { error($('[data-tasting-form-error]'), err.message); }); });
        $('[data-tasting-people-more]').addEventListener('click', function () { people(true).catch(function (err) { error($('[data-tasting-form-error]'), err.message); }); });
        $('[data-tasting-find-stock]').addEventListener('click', function () { choices(false).catch(function (err) { if (err.name !== 'AbortError') error($('[data-tasting-form-error]'), err.message); }); });
        $('[data-tasting-stock-more]').addEventListener('click', function () { choices(true).catch(function (err) { if (err.name !== 'AbortError') error($('[data-tasting-form-error]'), err.message); }); });
        $('[data-tasting-pool-more]').addEventListener('click', function () { loadPool(true).catch(function () {}); });
        $('[data-tasting-pool-retry]').addEventListener('click', function () { loadPool(state.poolRetryMore).catch(function () {}); });
        $('#tasting-task-type').addEventListener('change', function (event) {
            if (state.editing || event.target.value === 'tasting') return;
            captureDraft(); editor.close();
            var contact = state.choices.contacts.find(function (person) { return person.id === form.elements.contact_id.value; }) || {};
            root.dispatchEvent(new CustomEvent('tasting-draft-return', { bubbles: true, detail: {
                task_type: event.target.value, title: form.elements.title.value, description: form.elements.notes.value,
                due_date: form.elements.starts.value.slice(0, 10), assigned_to_user_id: form.elements.rep_id.value,
                contact_id: form.elements.contact_id.value,
                contact_name: form.elements.contact_id.selectedOptions[0]?.textContent || '',
                contact_email: contact.email_address || contact.email || '', contact_phone: contact.phone_number || contact.phone || '',
                assigned_to_name: form.elements.rep_id.selectedOptions[0]?.textContent || ''
            } }));
        });
        root._tastings = {
            create: function (seed, fresh) { if (fresh) state.draft = null; return openEditor(null, null, seed); },
            detail: openDetail,
            stock: function () { stockDialog.showModal(); loadPool().catch(function () {}); }
        };

    }
    window.__tastingsInit = init;
    if (!window.__tastingsShellBound) {
        window.__tastingsShellBound = true;
        document.addEventListener('htmx:afterSettle', function () { window.__tastingsInit(); });
        document.addEventListener('htmx:historyRestore', function () { window.__tastingsInit(); });
        document.addEventListener('htmx:beforeSwap', function (event) { var target = event.detail && event.detail.target; var root = document.querySelector(ROOT); if (target && target.id === 'page-content' && event.detail.shouldSwap !== false && root && root._tastingsAbort) root._tastingsAbort(); });
    }
    init();
})();
