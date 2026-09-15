/** Starter code snippets shown in the sandbox console. */

export const EXAMPLE_SNIPPETS = [
  {
    label: "data analysis",
    code: `import pandas as pd
import numpy as np

# Create sample data
df = pd.DataFrame({
    'date': pd.date_range('2024-01-01', periods=30),
    'revenue': np.random.uniform(1000, 5000, 30),
    'users': np.random.randint(100, 1000, 30)
})

print(df.describe())`,
  },
  {
    label: "chart",
    code: `import matplotlib.pyplot as plt
import numpy as np

x = np.linspace(0, 10, 100)
plt.figure(figsize=(8, 4))
plt.plot(x, np.sin(x), label='sin(x)')
plt.plot(x, np.cos(x), label='cos(x)')
plt.legend()
plt.title('Trigonometric Functions')
plt.grid(True, alpha=0.3)
plt.savefig('/tmp/chart.png', dpi=100, bbox_inches='tight')
print("Chart saved to /tmp/chart.png")`,
  },
  {
    label: "sql query",
    code: `# Query through the governed gateway
import requests
import os

resp = requests.post(f"{os.environ.get('SP_GATEWAY_URL', 'http://localhost:3300')}/api/query", json={
    "connection_name": "default",
    "sql": "SELECT * FROM users LIMIT 5",
    "row_limit": 100
})
print(resp.json())`,
  },
];
