-- Clear cached Edamam recipes (and meal-plan references) for a fresh image-cache test.
-- Keeps users, oauth_identities, and sessions intact.
-- Run: docker compose -f docker-compose.prod.yml exec -T db psql -U app -d app < scripts/clear_recipe_cache.sql

BEGIN;

DELETE FROM mealplans;
DELETE FROM ingredients;
DELETE FROM recipes;

-- Re-seed demo recipes (local /static/ images — no Edamam quota).
INSERT INTO recipes (
    id, api_id, name, image_url, calories, protein, carbs, fat, default_servings, created_at
) VALUES
    (1, 'demo.grain_bowl', 'Garden grain bowl', '/static/img/demo/bowl.jpg',
     420.0, 18.0, 55.0, 12.0, 2, NOW()),
    (2, 'demo.citrus_salmon', 'Citrus herb salmon', '/static/img/demo/salmon.jpg',
     560.0, 48.0, 8.0, 32.0, 4, NOW());

INSERT INTO ingredients (recipe_id, name, quantity, unit) VALUES
    (1, 'Quinoa', 1.0, 'cup'),
    (1, 'Kale', 2.0, 'cup'),
    (1, 'Lemon juice', 2.0, 'tbsp'),
    (2, 'Salmon fillet', 1.5, 'lb'),
    (2, 'Fresh dill', 2.0, 'tbsp'),
    (2, 'Orange zest', 1.0, 'tsp');

SELECT setval(
    pg_get_serial_sequence('recipes', 'id'),
    (SELECT COALESCE(MAX(id), 1) FROM recipes)
);

COMMIT;
