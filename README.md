# 🍽️ Foodie  
**Project:** Recipe Scaler and Meal Planner  

---

## 👥 Team & Roles
- **Sam** – server-side development, backend logic, API integration  
- **Asia** – client-side development, UI/UX, frontend implementation (JavaScript & CSS)  
- **Justin** – database management, security considerations, system design  

---

## 👤 Target User
This app is for people who want an easy way to plan their meals and adjust recipes without doing manual calculations. Their goal is to quickly build a weekly meal plan and automatically scale recipes based on how many servings they need.

---

## 🚀 MVP (Version 1)

The minimum viable product for this project is a simple Recipe Scaler and Meal Planner web app focused on generating meals and adjusting portions.

### Core Features:
- **Recipe search and selection using Edamam API**  
  Users can search for recipes and view basic details like ingredients and nutrition information.

- **Recipe scaling feature**  
  Users can adjust the number of servings, and the app automatically scales ingredient quantities.

- **Basic meal plan creation**  
  Users can assign selected recipes to days in a simple weekly planner view.

- **Nutrition display per recipe**  
  Show calories and basic macronutrients (protein, carbs, fat) per serving.

- **Simple user interface**  
  A clean and functional frontend where users can browse recipes, scale them, and build a meal plan.

---

## 🔌 External APIs

The primary API for this project is the **Edamam Recipe API**, which provides a ready-made recipe database along with nutrition data. This allows us to focus on building application features rather than maintaining our own dataset.

Edamam requires authentication using an app ID and API key. Its free tier is limited, supporting only a small number of users (around 10 monthly active users), with request limits per user per day and restrictions on caching or storing recipe data. Because of these constraints, it is best suited for a demo or portfolio project rather than large-scale production.

As a backup, we will use the **USDA FoodData Central API**. It also requires an API key but is fully free and provides higher rate limits (around 1,000 requests per hour per IP). However, it only includes raw food and nutrition data without recipes or images, meaning additional logic would be needed to support full meal-planning features.

---

## 💡 Why This Project

We chose to build a meal planner because it is a practical tool that solves a real everyday problem while also giving us a chance to work on meaningful technical challenges. Sam is particularly motivated by the opportunity to design a system that supports healthy eating habits and aligns with his interest in maintaining a balanced lifestyle. Justin is interested in building a tool he can also use personally to support a healthier routine after transitioning out of active duty military life, and he is especially curious about learning more about application security in a real-world project. Asia chose this project because she finds meal planning genuinely useful in her own life and often struggles with finding recipes; she is also excited to strengthen her frontend skills by working with JavaScript and CSS to create a polished, realistic user experience.

---
