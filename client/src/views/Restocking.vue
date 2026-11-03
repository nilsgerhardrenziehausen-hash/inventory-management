<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.budget') }}</div>
          <div class="stat-value">{{ formatMoney(budget) }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.plannedSpend') }}</div>
          <div class="stat-value">{{ formatMoney(plannedSpend) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remainingBudget') }}</div>
          <div class="stat-value">{{ formatMoney(remainingBudget) }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">{{ t('restocking.itemsToOrder') }}</div>
          <div class="stat-value">{{ recommendations.length }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.budgetSlider') }}</h3>
          <span class="budget-current">
            {{ t('restocking.currentBudget') }}: <strong>{{ formatMoney(budget) }}</strong>
          </span>
        </div>
        <input
          id="restocking-budget"
          v-model.number="budget"
          type="range"
          class="budget-slider"
          min="0"
          :max="maxBudget"
          :step="BUDGET_STEP"
          :disabled="maxBudget === 0"
          :aria-label="t('restocking.budgetSlider')"
        />
        <div class="slider-labels">
          <span>{{ t('restocking.sliderMin') }}: {{ formatMoney(0) }}</span>
          <span>{{ t('restocking.sliderMax') }}: {{ formatMoney(maxBudget) }}</span>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendations') }} ({{ recommendations.length }})</h3>
          <button
            type="button"
            class="place-order-btn"
            :disabled="recommendations.length === 0 || submitting"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.placingOrder') : t('restocking.placeOrder') }}
          </button>
        </div>

        <div v-if="submitError" class="error">{{ submitError }}</div>
        <div v-if="submittedOrder" class="success-message">
          {{ t('restocking.orderPlaced', {
            id: submittedOrder.id,
            total: formatMoney(submittedOrder.total_cost),
            date: formatDate(submittedOrder.expected_delivery)
          }) }}
          <router-link to="/orders" class="success-link">{{ t('restocking.viewOrders') }}</router-link>
        </div>

        <div v-if="recommendations.length === 0" class="empty-state">
          {{ t('restocking.noRecommendations') }}
        </div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.item') }}</th>
                <th>{{ t('restocking.table.category') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th class="num">{{ t('restocking.table.shortfall') }}</th>
                <th class="num">{{ t('restocking.table.orderQuantity') }}</th>
                <th class="num">{{ t('restocking.table.unitCost') }}</th>
                <th class="num">{{ t('restocking.table.lineTotal') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="rec in recommendations" :key="rec.sku">
                <td><strong>{{ rec.sku }}</strong></td>
                <td>{{ translateProductName(rec.name) }}</td>
                <td>{{ translateCategory(rec.category) }}</td>
                <td>
                  <span :class="['badge', rec.trend]">{{ t(`trends.${rec.trend}`) }}</span>
                </td>
                <td class="num">{{ rec.shortfall.toLocaleString() }}</td>
                <td class="num">
                  <strong>{{ rec.quantity.toLocaleString() }}</strong>
                  <span v-if="rec.quantity < rec.shortfall" class="partial-note">/ {{ rec.shortfall.toLocaleString() }}</span>
                </td>
                <td class="num">{{ formatMoney(rec.unit_cost) }}</td>
                <td class="num"><strong>{{ formatMoney(rec.line_total) }}</strong></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'

// Slider granularity and the rounding unit for the maximum / default budget
const BUDGET_STEP = 500

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, currentLocale, translateProductName } = useI18n()

    const currencySymbol = computed(() => {
      return currentCurrency.value === 'JPY' ? '¥' : '$'
    })

    const loading = ref(true)
    const error = ref(null)
    const forecasts = ref([])
    const budget = ref(0)

    const submitting = ref(false)
    const submitError = ref(null)
    const submittedOrder = ref(null)

    // Amounts are shown as returned by the API (no currency conversion), like Orders.vue
    const formatMoney = (amount) => `${currencySymbol.value}${Number(amount).toLocaleString()}`

    const formatDate = (dateString) => {
      const date = new Date(dateString)
      if (isNaN(date.getTime())) return ''
      const locale = currentLocale.value === 'ja' ? 'ja-JP' : 'en-US'
      return date.toLocaleDateString(locale, { year: 'numeric', month: 'short', day: 'numeric' })
    }

    const translateCategory = (category) => {
      const categoryMap = {
        'Circuit Boards': t('categories.circuitBoards'),
        'Sensors': t('categories.sensors'),
        'Actuators': t('categories.actuators'),
        'Controllers': t('categories.controllers'),
        'Power Supplies': t('categories.powerSupplies')
      }
      return categoryMap[category] || category
    }

    // Units missing versus forecasted demand (never negative)
    const getShortfall = (item) => Math.max(0, item.forecasted_demand - item.quantity_on_hand)

    // Items that actually need restocking
    const shortfallItems = computed(() => {
      return forecasts.value
        .map(item => ({ ...item, shortfall: getShortfall(item) }))
        .filter(item => item.shortfall > 0)
    })

    // Cost of restocking every shortfall, rounded UP to the next BUDGET_STEP so that
    // the top of the slider always means "restock everything"
    const maxBudget = computed(() => {
      const total = shortfallItems.value.reduce((sum, item) => sum + item.shortfall * item.unit_cost, 0)
      return Math.ceil(total / BUDGET_STEP) * BUDGET_STEP
    })

    // Greedy-by-urgency allocation: the biggest shortfalls are funded first (ties broken
    // by SKU). Each item gets as many units as the remaining budget allows, capped at its
    // shortfall, so the last affordable item may be a partial quantity. Items that cannot
    // afford a single unit are skipped. Math is done in integer cents to avoid float drift.
    const recommendations = computed(() => {
      const sorted = [...shortfallItems.value].sort((a, b) => {
        if (b.shortfall !== a.shortfall) return b.shortfall - a.shortfall
        return a.item_sku.localeCompare(b.item_sku)
      })

      let remainingCents = Math.round(budget.value * 100)
      const result = []
      for (const item of sorted) {
        const unitCents = Math.round(item.unit_cost * 100)
        if (unitCents <= 0) continue
        const quantity = Math.min(item.shortfall, Math.floor(remainingCents / unitCents))
        if (quantity <= 0) continue

        const lineCents = quantity * unitCents
        remainingCents -= lineCents
        result.push({
          sku: item.item_sku,
          name: item.item_name,
          category: item.category,
          trend: item.trend,
          shortfall: item.shortfall,
          quantity,
          unit_cost: item.unit_cost,
          line_total: lineCents / 100
        })
      }
      return result
    })

    const plannedSpend = computed(() => {
      return recommendations.value.reduce((sum, r) => sum + Math.round(r.line_total * 100), 0) / 100
    })

    const remainingBudget = computed(() => {
      return Math.round((budget.value - plannedSpend.value) * 100) / 100
    })

    const loadForecasts = async () => {
      try {
        loading.value = true
        error.value = null
        forecasts.value = await api.getDemandForecasts()
        // Default to half of the "restock everything" budget, on a slider step
        budget.value = Math.round((maxBudget.value * 0.5) / BUDGET_STEP) * BUDGET_STEP
      } catch (err) {
        error.value = t('restocking.loadFailed') + ': ' + err.message
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      if (recommendations.value.length === 0 || submitting.value) return
      submitting.value = true
      submitError.value = null
      submittedOrder.value = null
      try {
        submittedOrder.value = await api.createRestockingOrder({
          budget: budget.value,
          items: recommendations.value.map(r => ({ sku: r.sku, quantity: r.quantity }))
        })
      } catch (err) {
        submitError.value = err.response?.data?.detail || t('restocking.orderFailed')
        console.error('Failed to place restocking order:', err)
      } finally {
        submitting.value = false
      }
    }

    onMounted(loadForecasts)

    return {
      t,
      BUDGET_STEP,
      loading,
      error,
      budget,
      maxBudget,
      recommendations,
      plannedSpend,
      remainingBudget,
      submitting,
      submitError,
      submittedOrder,
      formatMoney,
      formatDate,
      translateCategory,
      translateProductName,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-current {
  color: #64748b;
  font-size: 0.938rem;
}

.budget-current strong {
  color: #0f172a;
}

/* Range slider: slate track, blue thumb (WebKit and Firefox) */
.budget-slider {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 20px;
  background: transparent;
  cursor: pointer;
  margin: 0.25rem 0;
}

.budget-slider:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.budget-slider::-webkit-slider-runnable-track {
  height: 6px;
  background: #cbd5e1;
  border-radius: 3px;
}

.budget-slider::-moz-range-track {
  height: 6px;
  background: #cbd5e1;
  border-radius: 3px;
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 20px;
  height: 20px;
  margin-top: -7px; /* centre the 20px thumb on the 6px track */
  border-radius: 50%;
  background: #2563eb;
  border: 2px solid white;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.35);
}

.budget-slider::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #2563eb;
  border: 2px solid white;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.35);
}

.budget-slider:focus-visible {
  outline: none;
}

.budget-slider:focus-visible::-webkit-slider-thumb {
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.35);
}

.budget-slider:focus-visible::-moz-range-thumb {
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.35);
}

.slider-labels {
  display: flex;
  justify-content: space-between;
  color: #64748b;
  font-size: 0.813rem;
}

.place-order-btn {
  background: #2563eb;
  color: white;
  border: none;
  border-radius: 8px;
  padding: 0.5rem 1.25rem;
  font-size: 0.875rem;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.15s ease;
}

.place-order-btn:hover:not(:disabled) {
  background: #1d4ed8;
}

.place-order-btn:disabled {
  background: #cbd5e1;
  color: #64748b;
  cursor: not-allowed;
}

.success-message {
  background: #ecfdf5;
  border: 1px solid #a7f3d0;
  color: #065f46;
  padding: 1rem;
  border-radius: 8px;
  margin: 0 0 1rem;
  font-size: 0.938rem;
}

.success-link {
  color: #2563eb;
  font-weight: 600;
  margin-left: 0.5rem;
}

.empty-state {
  text-align: center;
  padding: 2rem 1rem;
  color: #64748b;
  font-size: 0.938rem;
}

.num {
  text-align: right;
}

.partial-note {
  color: #64748b;
  font-size: 0.75rem;
  margin-left: 0.375rem;
}
</style>
