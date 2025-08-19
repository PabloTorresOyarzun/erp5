// Global JavaScript for Agencia de Aduanas ERP
// Shared functionality across all pages

// ==================== GLOBAL VARIABLES ====================
let sidebarCollapsed = localStorage.getItem('sidebarCollapsed') === 'true';

// ==================== ALERT SYSTEM ====================
window.showAlert = function(message, type = 'info', duration = 5000) {
    const alertContainer = document.getElementById('globalAlertContainer');
    const alertId = 'alert-' + Date.now();
    
    const alertColors = {
        success: 'alert-success',
        error: 'alert-danger',
        danger: 'alert-danger',
        warning: 'alert-warning',
        info: 'alert-info',
        primary: 'alert-primary'
    };
    
    const alertClass = alertColors[type] || 'alert-info';
    
    const alertElement = document.createElement('div');
    alertElement.id = alertId;
    alertElement.className = `alert ${alertClass} alert-dismissible fade show alert-global`;
    alertElement.innerHTML = `
        <div class="d-flex align-items-center">
            <i class="bi bi-${getAlertIcon(type)} me-2"></i>
            <span>${message}</span>
        </div>
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    alertContainer.appendChild(alertElement);
    
    // Auto-dismiss after duration
    if (duration > 0) {
        setTimeout(() => {
            if (document.getElementById(alertId)) {
                const alert = bootstrap.Alert.getOrCreateInstance(alertElement);
                alert.close();
            }
        }, duration);
    }
};

function getAlertIcon(type) {
    const icons = {
        success: 'check-circle-fill',
        error: 'exclamation-triangle-fill',
        danger: 'exclamation-triangle-fill',
        warning: 'exclamation-triangle-fill',
        info: 'info-circle-fill',
        primary: 'info-circle-fill'
    };
    return icons[type] || 'info-circle-fill';
}

// Replace native alert
window.originalAlert = window.alert;
window.alert = function(message) {
    showAlert(message, 'info');
};

// ==================== SIDEBAR FUNCTIONALITY ====================
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const mainContent = document.getElementById('mainContent');
    const overlay = document.getElementById('sidebarOverlay');
    
    if (!sidebar) return;
    
    // Ensure transitions are enabled
    sidebar.style.transition = '';
    if (mainContent) mainContent.style.transition = '';
    
    if (window.innerWidth <= 768) {
        sidebar.classList.toggle('show');
        if (overlay) overlay.classList.toggle('show');
        document.body.style.overflow = sidebar.classList.contains('show') ? 'hidden' : '';
    } else {
        sidebar.classList.toggle('collapsed');
        if (mainContent) mainContent.classList.toggle('sidebar-collapsed');
        sidebarCollapsed = sidebar.classList.contains('collapsed');
        localStorage.setItem('sidebarCollapsed', sidebarCollapsed);
        
        // Update CSS variable
        document.documentElement.style.setProperty('--sidebar-width', 
            sidebarCollapsed ? '70px' : '250px');
    }
}

function closeSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    
    if (sidebar) sidebar.classList.remove('show');
    if (overlay) overlay.classList.remove('show');
    document.body.style.overflow = '';
}

// ==================== INITIALIZATION ====================
document.addEventListener('DOMContentLoaded', function() {
    const sidebar = document.getElementById('sidebar');
    const mainContent = document.getElementById('mainContent');
    
    if (sidebar && window.innerWidth > 768) {
        // Apply state without transition
        if (sidebarCollapsed) {
            sidebar.classList.add('collapsed');
            if (mainContent) mainContent.classList.add('sidebar-collapsed');
        }
        
        // Enable transitions after 100ms
        setTimeout(function() {
            sidebar.style.transition = '';
            if (mainContent) mainContent.style.transition = '';
        }, 100);
    }
});

// ==================== EVENT LISTENERS ====================
window.addEventListener('resize', function() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');
    const mainContent = document.getElementById('mainContent');
    
    if (window.innerWidth > 768 && sidebar && overlay) {
        sidebar.classList.remove('show');
        overlay.classList.remove('show');
        document.body.style.overflow = '';
        
        if (sidebarCollapsed) {
            sidebar.classList.add('collapsed');
            if (mainContent) mainContent.classList.add('sidebar-collapsed');
        }
    }
});

// Prevent flicker when navigating
window.addEventListener('beforeunload', function() {
    const sidebar = document.getElementById('sidebar');
    const mainContent = document.getElementById('mainContent');
    
    if (sidebar) sidebar.style.transition = 'none';
    if (mainContent) mainContent.style.transition = 'none';
});

// ==================== UTILITY FUNCTIONS ====================
function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// ==================== ERROR PAGE FUNCTIONALITY ====================
window.initErrorPage = function(errorCode, redirectUrl) {
    // Auto-redirect after 10 seconds for 404 errors
    if (errorCode === 404) {
        setTimeout(function() {
            showAlert('Redirigiendo al inicio...', 'info', 3000);
            setTimeout(function() {
                window.location.href = redirectUrl;
            }, 3000);
        }, 10000);
    }
    
    // Prevent back navigation to error pages for critical errors
    if (errorCode === 403 || errorCode === 500) {
        window.history.replaceState(null, null, redirectUrl);
    }
};

// ==================== API HELPERS ====================
async function apiRequest(url, options = {}) {
    try {
        const response = await fetch(url, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            }
        });
        
        if (!response.ok) {
            const error = await response.json().catch(() => ({ error: 'Error de conexión' }));
            throw new Error(error.error || `Error ${response.status}`);
        }
        
        return await response.json();
    } catch (error) {
        throw error;
    }
}