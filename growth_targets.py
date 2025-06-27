def gin_sales():
    bottles_per_case = 6
    new_stores_per_week = 4

    weeks = int(input("Enter the number of weeks to calculate sales for: "))
    bottles_sold_per_store_per_week = int(input("Enter the number of bottles each new store is expected to sell per week: "))
    existing_stores = int(input("Enter the number of stores you are already selling to: "))
    weeks_to_restock = bottles_per_case // bottles_sold_per_store_per_week

    total_stores = existing_stores
    total_bottles_sold_to_stores = 0
    total_bottles_sold_to_public = 0
    weekly_bottle_sales_to_stores = []
    weekly_bottle_sales_to_public = []

    restocking_schedule = [1 + weeks_to_restock] * existing_stores  # All existing stores will restock in 'weeks_to_restock' weeks

    print(f"This data shows the bottle sales if we acquire {new_stores_per_week} new stores each week and they purchase 1 case of {bottles_per_case} bottles each, and anticipating each store will sell {bottles_sold_per_store_per_week} bottles per week and restock when sold out.")
    print(f"Additionally, starting with {existing_stores} existing stores that have all stocked up this week.\n")

    for week in range(1, weeks + 1):
        print(f"Week {week}:")

        # Add new stores
        total_stores += new_stores_per_week
        print(f"  Added {new_stores_per_week} new stores. Total stores: {total_stores}")

        # Schedule initial restocking for new stores
        for _ in range(new_stores_per_week):
            restocking_schedule.append(week + weeks_to_restock)

        # Calculate bottles sold to stores this week (initial sale)
        bottles_sold_to_stores_this_week = new_stores_per_week * bottles_per_case
        print(f"  Initial sales to new stores: {bottles_sold_to_stores_this_week} bottles")

        # Calculate restocking for previous stores
        restocking_this_week = restocking_schedule.count(week)
        bottles_sold_to_stores_this_week += restocking_this_week * bottles_per_case
        print(f"  Restocking sales: {restocking_this_week * bottles_per_case} bottles (from {restocking_this_week} stores)")

        # Accumulate total bottles sold to stores
        total_bottles_sold_to_stores += bottles_sold_to_stores_this_week
        weekly_bottle_sales_to_stores.append(bottles_sold_to_stores_this_week)

        # Calculate bottles sold by stores to the public this week
        bottles_sold_to_public_this_week = total_stores * bottles_sold_per_store_per_week
        print(f"  Bottles sold to the public: {bottles_sold_to_public_this_week} bottles")

        # Accumulate total bottles sold to the public
        total_bottles_sold_to_public += bottles_sold_to_public_this_week
        weekly_bottle_sales_to_public.append(bottles_sold_to_public_this_week)

        # Update restocking schedule for stores that need to restock every 'weeks_to_restock' weeks
        for _ in range(restocking_this_week):
            restocking_schedule.append(week + weeks_to_restock)

        print(f"  Total bottles sold to stores this week: {bottles_sold_to_stores_this_week} bottles")
        print(f"  Total bottles sold to the public this week: {bottles_sold_to_public_this_week} bottles\n")

    total_cases_sold_to_stores = total_bottles_sold_to_stores // bottles_per_case

    return {
        "weeks": weeks,
        "total_bottles_sold_to_stores": total_bottles_sold_to_stores,
        "total_cases_sold_to_stores": total_cases_sold_to_stores,
        "total_bottles_sold_to_public": total_bottles_sold_to_public,
        "total_stores": total_stores,
        "weekly_bottle_sales_to_stores": weekly_bottle_sales_to_stores,
        "weekly_bottle_sales_to_public": weekly_bottle_sales_to_public
    }

# Example usage:
result = gin_sales()
print(f"After {result['weeks']} weeks:")
print(f"Total bottles sold to stores: {result['total_bottles_sold_to_stores']}")
print(f"Total cases sold to stores: {result['total_cases_sold_to_stores']}")
print(f"Total bottles sold to the public: {result['total_bottles_sold_to_public']}")
print(f"Total stores: {result['total_stores']}")
print("Weekly bottle sales to stores breakdown:", result['weekly_bottle_sales_to_stores'])
print("Weekly bottle sales to the public breakdown:", result['weekly_bottle_sales_to_public'])
