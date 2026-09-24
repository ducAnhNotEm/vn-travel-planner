# Route Optimization Skill (Spatial Routing & Clustering)

## Purpose
Order destinations within a day to minimize total distance and prevent zigzag/backtracking routes.

## Multi-Day Rule: Clustering BEFORE Routing
For multi-day trips ($\ge 2$ days):
1. **Step 1 - Spatial Clustering**: Group all unassigned destinations into $N$ clusters (where $N = \text{number of days}$) using coordinate centroids (`lat`, `lng`).
   - Cluster 1 $\rightarrow$ Day 1
   - Cluster 2 $\rightarrow$ Day 2
2. **Step 2 - Intra-day Sequencing (TSP)**:
   - Fix Departure point (or Morning Hotel) as Anchor Start $S_0$.
   - Apply Greedy Nearest Neighbor or 2-Opt Algorithm to sequence destinations:
     $$S_0 \rightarrow P_1 \rightarrow P_2 \rightarrow \dots \rightarrow P_k \rightarrow S_{end}$$
   - Respect functional category sequence (Breakfast/Departure $\rightarrow$ Morning Sightseeing $\rightarrow$ Lunch $\rightarrow$ Afternoon Sightseeing $\rightarrow$ Dinner $\rightarrow$ Hotel).

## Haversine Distance Formula
All point-to-point distances must be calculated via:
```python
def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0 # Earth radius km
    # standard haversine trigonometry
```
Average urban/provincial transit speed:
- Car/Taxi: $35\text{ km/h}$
- Motorbike: $30\text{ km/h}$
- Bus: $25\text{ km/h}$

$$\text{Travel time (minutes)} = \frac{\text{Distance (km)}}{\text{Speed (km/h)}} \times 60$$
