#include <SDL2/SDL.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#define W 800
#define H 600
#define CELL 20
#define COLS (W / CELL)
#define ROWS (H / CELL)
#define MAX_SEG (COLS * ROWS)

typedef struct { int x, y; } Cell;
static Cell body[MAX_SEG];
static int length, dx, dy, food_x, food_y, score;
static bool game_over, running;
static Uint32 next_step;
static SDL_Window *window;
static SDL_Renderer *renderer;

static bool occupied(int x, int y) {
  for (int i = 0; i < length; i++) if (body[i].x == x && body[i].y == y) return true;
  return false;
}
static void place_food(void) {
  int free_count = COLS * ROWS - length;
  if (free_count <= 0) { game_over = true; return; }
  int pick = rand() % free_count;
  for (int y = 0; y < ROWS; y++) for (int x = 0; x < COLS; x++)
    if (!occupied(x, y) && pick-- == 0) { food_x = x; food_y = y; return; }
}
static void reset_game(void) {
  length = 3; body[0] = (Cell){COLS/2, ROWS/2}; body[1] = (Cell){COLS/2-1, ROWS/2}; body[2] = (Cell){COLS/2-2, ROWS/2};
  dx = 1; dy = 0; score = 0; game_over = false; next_step = SDL_GetTicks() + 120; place_food();
}
static void turn(int ndx, int ndy) {
  if (!game_over && !(ndx == -dx && ndy == -dy)) { dx = ndx; dy = ndy; }
}
static void step_game(void) {
  if (game_over) return;
  Cell head = {body[0].x + dx, body[0].y + dy};
  if (head.x < 0 || head.x >= COLS || head.y < 0 || head.y >= ROWS || occupied(head.x, head.y)) { game_over = true; return; }
  bool eating = head.x == food_x && head.y == food_y;
  int new_length = length + (eating ? 1 : 0);
  if (new_length > MAX_SEG) new_length = MAX_SEG;
  for (int i = new_length - 1; i > 0; i--) body[i] = body[i - 1];
  body[0] = head; length = new_length;
  if (eating) { score++; place_food(); }
}
static void draw_text(SDL_Renderer *r, const char *text, int x, int y, SDL_Color color) {
  /* Tiny bitmap-free score panel: text is drawn by SDL window title for portability. */
  (void)r; (void)text; (void)x; (void)y; (void)color;
}
static void draw(void) {
  SDL_SetRenderDrawColor(renderer, 12, 18, 28, 255); SDL_RenderClear(renderer);
  SDL_Rect f = {food_x*CELL+2, food_y*CELL+2, CELL-4, CELL-4};
  SDL_SetRenderDrawColor(renderer, 230, 70, 70, 255); SDL_RenderFillRect(renderer, &f);
  for (int i = length-1; i >= 0; i--) { SDL_Rect q={body[i].x*CELL+1,body[i].y*CELL+1,CELL-2,CELL-2}; SDL_SetRenderDrawColor(renderer, i==0?60:40, i==0?220:180, i==0?100:80,255); SDL_RenderFillRect(renderer,&q); }
  SDL_SetWindowTitle(window, game_over ? "Snake — GAME OVER (Space/Enter to restart, Esc to quit)" : "Snake — Score: (see terminal) | WASD / arrows");
  SDL_RenderPresent(renderer);
}

/* Exported native entry point called by the compact Coil entry module. */
int64_t snake_window_run(void) {
  if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_TIMER) != 0) return 1;
  window = SDL_CreateWindow("Snake", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, W, H, SDL_WINDOW_SHOWN);
  renderer = window ? SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC) : NULL;
  if (!window || !renderer) { SDL_Quit(); return 2; }
  srand((unsigned)time(NULL)); reset_game(); running = true;
  while (running) {
    SDL_Event e;
    while (SDL_PollEvent(&e)) {
      if (e.type == SDL_QUIT) running = false;
      if (e.type == SDL_KEYDOWN) {
        switch (e.key.keysym.sym) {
          case SDLK_ESCAPE: running = false; break;
          case SDLK_UP: case SDLK_w: turn(0,-1); break;
          case SDLK_DOWN: case SDLK_s: turn(0,1); break;
          case SDLK_LEFT: case SDLK_a: turn(-1,0); break;
          case SDLK_RIGHT: case SDLK_d: turn(1,0); break;
          case SDLK_SPACE: case SDLK_RETURN: if (game_over) reset_game(); break;
        }
      }
    }
    Uint32 now = SDL_GetTicks();
    if (!game_over && now >= next_step) { step_game(); next_step = now + 120; printf("score=%d\n", score); fflush(stdout); }
    draw(); SDL_Delay(4);
  }
  SDL_DestroyRenderer(renderer); SDL_DestroyWindow(window); SDL_Quit(); return 0;
}

/* Deterministic self-test for core transitions, used by `make test`. */
int snake_self_test(void) {
  length=3; body[0]=(Cell){3,3}; body[1]=(Cell){2,3}; body[2]=(Cell){1,3}; dx=1;dy=0;food_x=5;food_y=3;score=0;game_over=false;
  step_game(); if (body[0].x != 4 || length != 3) return 1;
  food_x=5; food_y=3; step_game(); if (body[0].x != 5 || length != 4 || score != 1) return 2;
  body[0]=(Cell){0,0}; body[1]=(Cell){1,0}; body[2]=(Cell){2,0}; length=3;dx=-1;dy=0;game_over=false; step_game(); if (!game_over) return 3;
  body[0]=(Cell){3,3};body[1]=(Cell){3,4};body[2]=(Cell){4,3};length=3;dx=0;dy=1;game_over=false;step_game();if(!game_over)return 4;
  return 0;
}
