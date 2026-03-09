/**
 * ATELIER — Fashion Virtual Try-On
 * Application State & API Layer
 */
const API_BASE = ((window.__CONFIG__ && window.__CONFIG__.API_BASE) || localStorage.getItem('api_url') || '').replace(/\/+$/, '');

const App = {
  user: null,
  token: null,
  products: [],

  init() {
    this.token = localStorage.getItem('auth_token');
    this.refreshToken = localStorage.getItem('refresh_token');
    this.user = JSON.parse(localStorage.getItem('user') || 'null');
  },

  updateNav() {
    document.querySelectorAll('.nav__user').forEach(el => {
      if (this.user) {
        el.textContent = this.user.name || this.user.email || 'Account';
      } else if (this.isGuest()) {
        el.textContent = 'Guest';
      } else {
        el.textContent = '';
      }
    });
    document.querySelectorAll('#authBtn').forEach(el => {
      el.textContent = this.isLoggedIn() || this.isGuest() ? 'Logout' : 'Sign In';
    });
  },

  isGuest() { return localStorage.getItem('guest') === 'true'; },
  isLoggedIn() { return !!this.token; },

  setAuth(token, user, refreshToken) {
    this.token = token;
    this.refreshToken = refreshToken || this.refreshToken;
    this.user = user;
    localStorage.setItem('auth_token', token);
    if (refreshToken) localStorage.setItem('refresh_token', refreshToken);
    localStorage.setItem('user', JSON.stringify(user));
    localStorage.removeItem('guest');
    this.updateNav();
  },

  continueAsGuest() {
    localStorage.setItem('guest', 'true');
    localStorage.removeItem('auth_token');
    localStorage.removeItem('user');
    this.token = null;
    this.user = null;
    this.updateNav();
  },

  logout() {
    localStorage.clear();
    this.token = null;
    this.user = null;
    window.location.href = 'login.html';
  },

  async refreshAuth() {
    if (!this.refreshToken) return false;
    const REGION = 'ap-southeast-1';
    const CLIENT_ID = '6fi26nna2kg0q926k4gk9upeag';
    try {
      const res = await fetch(`https://cognito-idp.${REGION}.amazonaws.com/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-amz-json-1.1', 'X-Amz-Target': 'AWSCognitoIdentityProviderService.InitiateAuth' },
        body: JSON.stringify({ AuthFlow: 'REFRESH_TOKEN_AUTH', ClientId: CLIENT_ID, AuthParameters: { REFRESH_TOKEN: this.refreshToken } })
      });
      if (!res.ok) return false;
      const data = await res.json();
      this.token = data.AuthenticationResult.IdToken;
      localStorage.setItem('auth_token', this.token);
      return true;
    } catch { return false; }
  },

  async api(path, options = {}) {
    const headers = { 'Content-Type': 'application/json' };
    if (this.token) headers['Authorization'] = this.token;
    const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
    if (res.status === 401 && await this.refreshAuth()) {
      headers['Authorization'] = this.token;
      const retry = await fetch(`${API_BASE}${path}`, { ...options, headers });
      const data = await retry.json();
      if (!retry.ok) throw new Error(data.error || 'Request failed');
      return data;
    }
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Request failed');
    return data;
  },

  toast(msg, isError = false) {
    const el = document.createElement('div');
    el.className = `toast${isError ? ' toast--error' : ''}`;
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }
};

// Demo product data (used when API is not connected)
const DEMO_PRODUCTS = [
  { product_id: '1', name: 'Oversized Wool Blazer', category: 'outerwear', price: '289', garment_class: 'UPPER_BODY', sizes: ['S','M','L'], colors: ['Black','Camel'], image_url: 'https://images.unsplash.com/photo-1591047139829-d91aecb6caea?w=600&h=800&fit=crop' },
  { product_id: '2', name: 'Silk Drape Shirt', category: 'tops', price: '165', garment_class: 'UPPER_BODY', sizes: ['XS','S','M','L'], colors: ['Ivory','Black'], image_url: 'https://images.unsplash.com/photo-1598300042247-d088f8ab3a91?w=600&h=800&fit=crop' },
  { product_id: '3', name: 'Tailored Wide Trousers', category: 'bottoms', price: '195', garment_class: 'LOWER_BODY', sizes: ['S','M','L','XL'], colors: ['Charcoal','Navy'], image_url: 'https://images.unsplash.com/photo-1594938298603-c8148c4dae35?w=600&h=800&fit=crop' },
  { product_id: '4', name: 'Cashmere Crew Knit', category: 'tops', price: '220', garment_class: 'UPPER_BODY', sizes: ['S','M','L'], colors: ['Oat','Grey'], image_url: 'https://images.unsplash.com/photo-1576566588028-4147f3842f27?w=600&h=800&fit=crop' },
  { product_id: '5', name: 'Leather Moto Jacket', category: 'outerwear', price: '450', garment_class: 'UPPER_BODY', sizes: ['S','M','L'], colors: ['Black'], image_url: 'https://images.unsplash.com/photo-1551028719-00167b16eac5?w=600&h=800&fit=crop' },
  { product_id: '6', name: 'Pleated Midi Skirt', category: 'bottoms', price: '145', garment_class: 'LOWER_BODY', sizes: ['XS','S','M','L'], colors: ['Black','Burgundy'], image_url: 'https://images.unsplash.com/photo-1583496661160-fb5886a0aaaa?w=600&h=800&fit=crop' },
  { product_id: '7', name: 'Structured Linen Dress', category: 'dresses', price: '275', garment_class: 'FULL_BODY', sizes: ['S','M','L'], colors: ['White','Sage'], image_url: 'https://images.unsplash.com/photo-1595777457583-95e059d581b8?w=600&h=800&fit=crop' },
  { product_id: '8', name: 'Minimal Leather Boots', category: 'footwear', price: '340', garment_class: 'FOOTWEAR', sizes: ['36','37','38','39','40','41'], colors: ['Black','Tan'], image_url: 'https://images.unsplash.com/photo-1543163521-1bf539c55dd2?w=600&h=800&fit=crop' },
];

async function loadProducts() {
  try {
    const data = await App.api('/products');
    return data.products || [];
  } catch {
    return DEMO_PRODUCTS;
  }
}

App.init();
document.addEventListener('DOMContentLoaded', () => App.updateNav());
