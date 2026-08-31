// --- ЗАГРУЗКА И ИНИЦИАЛИЗАЦИЯ ---
document.addEventListener('DOMContentLoaded', async () => {
    const statusEl = document.getElementById('loader-status');
    const loaderEl = document.getElementById('loader');

    try {
        if (statusEl) statusEl.innerText = "Подключение к базам данных...";

        // Запуск проверок в Python
        const result = await eel.run_initial_checks()();

        if (result.success) {
            if (statusEl) statusEl.innerText = result.message;

            // Задержка для визуального перехода
            setTimeout(() => {
                if (loaderEl) loaderEl.classList.add('hidden');
            }, 600);
        } else if (result.new_version) {
            // Показываем диалог обновления
            showNewVersionAvailable(result.new_version, result.local_version);
        } else {
            if (statusEl) {
                statusEl.innerText = `Ошибка инициализации: ${result.message}`;
                statusEl.style.color = "#f75a68";
            }
        }
    } catch (err) {
        console.error("Ошибка при запуске:", err);
        if (statusEl) {
            statusEl.innerText = "Не удалось связаться с Python API";
            statusEl.style.color = "#f75a68";
        }
    }

    syncScroll();

    document.querySelectorAll('.copy-col-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const col = parseInt(btn.dataset.col, 10);
            copyColumnRaskatka(col);
        });
    });
});

let raskatkaTableData = [];

// --- ЛОГИКА ВЕРСИИ И ОБНОВЛЕНИЯ ---

function showNewVersionAvailable(newVer, localVer) {
    const overlay = document.getElementById('version-overlay');
    const newVerText = document.getElementById('new-version-text');
    const localVerText = document.getElementById('local-version-text');
    if (newVerText) newVerText.innerText = newVer;
    if (localVerText) localVerText.innerText = localVer;
    if (overlay) overlay.classList.remove('hidden');
}

async function doUpdate() {
    const overlay = document.getElementById('version-overlay');
    const statusEl = document.getElementById('loader-status');
    const spinnerEl = document.getElementById('spinner');

    if (overlay) overlay.classList.add('hidden');
    if (statusEl) statusEl.innerText = "Скачивание и установка обновления...";
    if (spinnerEl) spinnerEl.classList.remove('hidden');

    const res = await eel.update_app()();

    if (res && res.success) {
        if (statusEl) statusEl.innerText = "Обновление установлено! Перезапуск...";
        
        setTimeout(() => {
            // Отправляем команду на запуск нового процесса
            eel.restart_app()();
            
            // Сразу же закрываем текущее окно UI
            setTimeout(() => { 
                window.close(); 
            }, 100);
            
        }, 1200);
    } else {
        if (statusEl) {
            statusEl.innerText = `Ошибка обновления: ${res ? res.message : 'Неизвестная ошибка'}`;
            statusEl.style.color = "#f75a68";
        }
    }
}

function skipUpdate() {
    const overlay = document.getElementById('version-overlay');
    if (overlay) overlay.classList.add('hidden');
    const loaderEl = document.getElementById('loader');
    if (loaderEl) loaderEl.classList.add('hidden');
}

// --- ЛОГИКА ПРЕЛОАДЕРА И ЛОГОВ ---

eel.expose(addLog);
function addLog(message) {
    const logBox = document.getElementById('console-logs');
    if (logBox) {
        const line = document.createElement('div');
        line.textContent = message;
        logBox.appendChild(line);
        logBox.scrollTop = logBox.scrollHeight;
    } else {
        const loaderStatus = document.getElementById('loader-status');
        if (loaderStatus && !loaderStatus.innerText.startsWith("Загрузка")) {
            loaderStatus.innerText = message;
        }
    }
}

// --- ЛОГИКА ПЕРЕКЛЮЧЕНИЯ ВКЛАДОК ---
function switchTab(tabId) {
    const sections = document.querySelectorAll('.tab-section');
    sections.forEach(sec => sec.classList.add('hidden-element'));
    sections.forEach(sec => sec.classList.remove('active'));

    const tabs = document.querySelectorAll('.me');
    tabs.forEach(tab => tab.classList.remove('active'));

    const activeSection = document.getElementById(tabId);
    if (activeSection) {
        activeSection.classList.remove('hidden-element');
        activeSection.classList.add('active');
    }

    const activeBtnId = 'tab-' + tabId.replace('-tool', '');
    const activeBtn = document.getElementById(activeBtnId);
    if (activeBtn) activeBtn.classList.add('active');


    const statusBox = document.getElementById('status_box');
    if (statusBox) {
        const activeButtonWrapper = activeSection.querySelector('.button-wrapper');
        if (activeButtonWrapper) {
            activeButtonWrapper.appendChild(statusBox);
        }
    }

    setTimeout(syncScroll, 100);
}

// --- ОСНОВНАЯ ЛОГИКА Дополнение таблицы ---
let isSearching = false;
let cityList = [];
let regionList = [];
let currentIndex = -1;
let currentCityFound = false;

function toggleCustomSearchInputSearch() {
    const type = document.getElementById('search_search_type').value;
    const customQuery = document.getElementById('search_custom_query');
    if (type === 'custom') {
        customQuery.classList.remove('hidden-element');
    } else {
        customQuery.classList.add('hidden-element');
    }
}

async function handleSearchCycle() {
    const btn = document.getElementById('search_btn_main_action');
    
    if (!isSearching) {
        cityList = document.getElementById('search_cities').value.trim().split('\n').filter(x => x);
        regionList = document.getElementById('search_regions').value.trim().split('\n');
        
        if (cityList.length === 0) {
            alert("Введите хотя бы один город");
            return;
        }

        isSearching = true;
        currentIndex = 0;
        clearAllFields();
        document.getElementById('search_skipped_cities').value = "";
        
        btn.innerText = "Следующий";
        document.getElementById('search_btn_capture').disabled = false;
        document.getElementById('search_btn_save').disabled = false;
        
        startPythonIteration();
    } else {
        if (!currentCityFound) {
            const city = cityList[currentIndex];
            const region = regionList[currentIndex] || "";
            document.getElementById('search_skipped_cities').value += (region ? `${city}, ${region}\n` : `${city}\n`);
        }

        currentIndex++;
        if (currentIndex < cityList.length) {
            if (currentIndex === cityList.length - 1) {
                btn.innerText = "Конец";
            }
            currentCityFound = false;
            clearOutputFields();
            startPythonIteration();
        } else {
            isSearching = false;
            btn.innerText = "Поиск";
            document.getElementById('search_btn_capture').disabled = true;
            document.getElementById('search_btn_save').disabled = true;
            updateStatus("Ожидание действий пользователя");
        }
    }
}

function startPythonIteration() {
    const city = cityList[currentIndex];
    const region = regionList[currentIndex] || "";
    const searchType = document.getElementById('search_search_type').value;
    const customText = document.getElementById('search_custom_query').value;
    
    eel.process_search_iteration(city, region, searchType, customText)();
}

async function captureCurrentData() {
    let data = await eel.capture_map_data()();
    if (data) {
        const outCity = document.getElementById('search_out_city');
        outCity.value = data.city || "";
        const outTranslit = document.getElementById('search_out_translit');
        outTranslit.value = data.translit_city || "";
        
        if (data.city_warning) {
            outCity.classList.add('warning-input');
            outTranslit.classList.add('warning-input');
        } else {
            outCity.classList.remove('warning-input');
            outTranslit.classList.remove('warning-input');
        }

        const outType = document.getElementById('search_out_type');
        outType.value = data.typeNP || "";
        if (data.type_warning) {
            outType.classList.add('warning-input');
        } else {
            outType.classList.remove('warning-input');
        }

        document.getElementById('search_out_region').value = data.region || "";
        document.getElementById('search_out_full_address').value = data.full_address || "";
        document.getElementById('search_out_coords').value = data.coords || "";
        document.getElementById('search_out_index').value = data.index || "";
        document.getElementById('search_out_comm').value = data.comm || "";

        const outAddress = document.getElementById('search_out_address');
        outAddress.value = data.address || "";
        if (data.address_warning) {
            outAddress.classList.add('warning-input');
        } else {
            outAddress.classList.remove('warning-input');
        }
    }
}

async function saveDataToTable() {
    const data = {
        city: document.getElementById('search_out_city').value,
        translit_city: document.getElementById('search_out_translit').value,
        typeNP: document.getElementById('search_out_type').value,
        region: document.getElementById('search_out_region').value,
        address: document.getElementById('search_out_address').value,
        full_address: document.getElementById('search_out_full_address').value,
        coords: document.getElementById('search_out_coords').value,
        index: document.getElementById('search_out_index').value,
        comm: document.getElementById('search_out_comm').value
    };

    let result = await eel.save_captured_data(data)();
    if (result === "success") {
        currentCityFound = true;
    }
}

function clearOutputFields() {
    const fields = ['search_out_city', 'search_out_translit', 'search_out_type', 'search_out_region', 'search_out_address', 'search_out_full_address', 'search_out_coords', 'search_out_index', 'search_out_comm'];
    fields.forEach(id => { if(document.getElementById(id)) document.getElementById(id).value = ""; });

    if(document.getElementById('search_out_city')) document.getElementById('search_out_city').classList.remove('warning-input');
    if(document.getElementById('search_out_translit')) document.getElementById('search_out_translit').classList.remove('warning-input');
    if(document.getElementById('search_out_address')) document.getElementById('search_out_address').classList.remove('warning-input');
    if(document.getElementById('search_out_type')) document.getElementById('search_out_type').classList.remove('warning-input');
}

function clearAllFields() {
    clearOutputFields();
}

function btnSborStart() {
    updateStatus("Запуск сбора дополнений")
    document.getElementById('sbor_btn_start').disabled = true;

    const fields = ['sbor_translit', 'sbor_coords', 'sbor_out_regions', 'sbor_index', 'sbor_errors'];
    fields.forEach(id => { if(document.getElementById(id)) document.getElementById(id).value = ""; });

    let addresses = document.getElementById('sbor_adresses').value.split('\n');
    let cities = document.getElementById('sbor_cities').value.split('\n');
    let regions = document.getElementById('sbor_regions').value.split('\n');

    eel.sbor_start_func(addresses, cities, regions)();
}

eel.expose(enableSborButton);
function enableSborButton() {
    document.getElementById('sbor_btn_start').disabled = false;
}

/// --- Раскатка --- ///
function btnRaskatkaStart() {
    updateStatus("Запуск раскатки")
    document.getElementById('raskatka_btn_start').disabled = true;

    const fields = ['raskatka_adresses', 'raskatka_translit', 'raskatka_out_regions', 'raskatka_coords', 'raskatka_index', 'raskatka_errors'];
    fields.forEach(id => { if(document.getElementById(id)) document.getElementById(id).value = ""; });

    let cities = document.getElementById('raskatka_cities').value.split('\n');
    let regions = document.getElementById('raskatka_regions').value.split('\n');
    let comm = document.getElementById('raskatka_comm').value.split('\n');
    const base = document.getElementById('raskatka_search_type').value;

    eel.raskatka_start_func(cities, regions, comm, base)();
}

eel.expose(enableRaskatkaButton);
function enableRaskatkaButton() {
    document.getElementById('raskatka_btn_start').disabled = false;
}

eel.expose(updateRaskatkaResults);
function updateRaskatkaResults(addresses, translits, regions, coords, indexes, errors) {
    const tbody = document.getElementById('raskatka-results-body');
    if (!tbody) return;

    const maxLen = Math.max(
        addresses.length,
        translits.length,
        regions.length,
        coords.length,
        indexes.length,
        errors.length
    );

    raskatkaTableData = [];
    tbody.innerHTML = '';

    for (let i = 0; i < maxLen; i++) {
        const row = {
            address: addresses[i] || '',
            translit: translits[i] || '',
            region: regions[i] || '',
            coords: coords[i] || '',
            index: indexes[i] || '',
            error: errors[i] || ''
        };
        raskatkaTableData.push(row);

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td title="${escapeHtml(row.address)}">${escapeHtml(row.address)}</td>
            <td title="${escapeHtml(row.translit)}">${escapeHtml(row.translit)}</td>
            <td title="${escapeHtml(row.region)}">${escapeHtml(row.region)}</td>
            <td title="${escapeHtml(row.coords)}">${escapeHtml(row.coords)}</td>
            <td title="${escapeHtml(row.index)}">${escapeHtml(row.index)}</td>
        `;
        tbody.appendChild(tr);
    }

    const errArea = document.getElementById('raskatka_errors');
    if (errArea) {
        errArea.value = errors.filter(e => e && e.trim() !== '').join('\n');
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function copyColumnRaskatka(colIndex) {
    const colNames = ['Адрес', 'Транслит', 'Регион', 'Координаты', 'Индекс'];
    const values = raskatkaTableData.map(row => {
        switch(colIndex) {
            case 0: return row.address;
            case 1: return row.translit;
            case 2: return row.region;
            case 3: return row.coords;
            case 4: return row.index;
        }
    }).filter(v => v !== '');

    const text = values.join('\n');
    navigator.clipboard.writeText(text).then(() => {
        const btn = document.querySelector(`.copy-col-btn[data-col="${colIndex}"]`);
        if (btn) showCopiedFeedback(btn, colNames[colIndex]);
    }).catch(err => {
        console.error('Ошибка копирования:', err);
        alert('Не удалось скопировать: ' + err);
    });
}

function copyAllRaskatkaTable() {
    if (raskatkaTableData.length === 0) {
        alert('Таблица пуста');
        return;
    }

    const headers = ['Адрес', 'Транслит', 'Регион', 'Координаты', 'Индекс'];
    const rows = raskatkaTableData.map(row => [
        row.address,
        row.translit,
        row.region,
        row.coords,
        row.index
    ]);

    const tsv = [headers.join('\t'), ...rows.map(r => r.join('\t'))].join('\n');
    
    navigator.clipboard.writeText(tsv).then(() => {
        const btn = document.getElementById('raskatka_copy_all');
        if (btn) showCopiedFeedback(btn, 'Вся таблица');
    }).catch(err => {
        console.error('Ошибка копирования таблицы:', err);
        alert('Не удалось скопировать таблицу: ' + err);
    });
}

function showCopiedFeedback(btn, label) {
    const originalText = btn.innerText;
    const suffix = label === 'Вся таблица' ? 'а' : '';
    btn.innerText = `✓ ${label} скопирован${suffix}`;
    btn.classList.add('copied');
    btn.disabled = true;
    setTimeout(() => {
        btn.innerText = originalText;
        btn.classList.remove('copied');
        btn.disabled = false;
    }, 2000);
}

eel.expose(update_sbor_output);
function update_sbor_output(translit, coords, regions, index, error_msg) {
    let t_field = document.getElementById('sbor_translit');
    let c_field = document.getElementById('sbor_coords');
    let r_field = document.getElementById('sbor_out_regions');
    let i_field = document.getElementById('sbor_index');
    let err_field = document.getElementById('sbor_errors');

    t_field.value += (t_field.value ? "\n" : "") + translit;
    c_field.value += (c_field.value ? "\n" : "") + coords;
    r_field.value += (r_field.value ? "\n" : "") + regions;
    i_field.value += (i_field.value ? "\n" : "") + index;
    if (error_msg && error_msg.trim() !== "") {
        err_field.value += (err_field.value ? "\n" : "") + error_msg;
    }
}

// Функция для синхронизации прокрутки
function syncScroll() {
    const textareas = document.querySelectorAll('.sync-scroll');
    
    textareas.forEach(textarea => {
        textarea.addEventListener('scroll', function() {
            const scrollPercentage = this.scrollTop / (this.scrollHeight - this.clientHeight);
            
            textareas.forEach(otherTextarea => {
                if (otherTextarea !== this) {
                    otherTextarea.scrollTop = scrollPercentage * (otherTextarea.scrollHeight - otherTextarea.clientHeight);
                }
            });
        });
    });
}

// --- ЛОГИКА СТАТУСОВ И ТАЙМЕРОВ ---
let statusCountdownInterval = null;
let lastStableMessage = "Ожидание действий пользователя";

eel.expose(showTempStatusWithTimer);
function showTempStatusWithTimer(message, seconds) {
    if (statusCountdownInterval) clearInterval(statusCountdownInterval);

    const statusBox = document.getElementById('status_box');
    if (statusBox && !message.includes("✅") && !message.includes("❌")) {
        const currentText = statusBox.innerText.replace(/\s\(\d+\)$/, "");
        if (currentText && !currentText.includes("✅") && !currentText.includes("❌")) {
            lastStableMessage = currentText;
        }
    }

    const fallbackMessage = lastStableMessage;
    let timeLeft = seconds;
    updateStatus(`${message} (${timeLeft})`, true);

    statusCountdownInterval = setInterval(() => {
        timeLeft--;
        if (timeLeft > 0) {
            updateStatus(`${message} (${timeLeft})`, true);
        } else {
            clearInterval(statusCountdownInterval);
            statusCountdownInterval = null;
            updateStatus(fallbackMessage); 
        }
    }, 1000);
}

eel.expose(updateStatus);
function updateStatus(message, isCountdownTick = false) {
    try {
        if (!isCountdownTick && statusCountdownInterval) {
            clearInterval(statusCountdownInterval);
            statusCountdownInterval = null;
        }

        const statusBox = document.getElementById('status_box');
        if (!statusBox) return;
        const msgStr = String(message || "");
        statusBox.innerText = msgStr;
        
        if (msgStr.includes("❌")) {
            statusBox.style.borderColor = "darkred";
            statusBox.style.color = "red";
        } else if (msgStr.includes("✅")) {
            statusBox.style.borderColor = "green";
            statusBox.style.color = "green";
        } else {
            statusBox.style.borderColor = "#ccc";
            statusBox.style.color = "#333";
        }

        let hasDots = false;
        if (
            msgStr.includes("Ожидание") || 
            msgStr.includes("Выберите") || 
            msgStr.includes("❌") || 
            msgStr.includes("✅")
        ) {
            statusBox.classList.remove('loading-dots');
        } else {
            statusBox.classList.add('loading-dots');
            hasDots = true;
        }

        if (!isCountdownTick && !hasDots && !msgStr.includes("❌") && !msgStr.includes("✅")) {
            lastStableMessage = msgStr;
        }
    } catch (error) {
        console.error("Ошибка в updateStatus:", error);
    }
}