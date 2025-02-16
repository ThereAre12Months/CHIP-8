import pygame
import random
import os, sys
import tomllib

class Emulator:
    def __init__(self, config=None):
        pygame.init()

        # GRAPHICS CONFIG
        gfx_config = (config or {}).get("GRAPHICS", {})
        self.output_resolution     = gfx_config.get("output_resolution",     [640, 320])
        self.preserve_aspect_ratio = gfx_config.get("preserve_aspect_ratio", True)
        self.fullscreen            = gfx_config.get("fullscreen",            False)
        self.resizable             = gfx_config.get("resizable",             True)
        self.scaling_method        = gfx_config.get("scaling_method",        "nearest")
        self.bg_color              = gfx_config.get("bg_color",              (50, 50, 50))
        self.off_color             = gfx_config.get("off_color",             (0, 0, 0))
        self.on_color              = gfx_config.get("on_color",              (255, 255, 255))

        # DEBUG CONFIG
        dbg_config = (config or {}).get("DEBUG", {})
        self.show_fps       = dbg_config.get("show_fps",       False)
        self.live_mem_view  = dbg_config.get("live_mem_view",  False)
        self.mem_view_scale = dbg_config.get("mem_view_scale", 2)

        # SYSTEM CONFIG
        sys_config = (config or {}).get("SYSTEM", {})
        self.resolution = sys_config.get("resolution", [64, 32])
        self.vsync = sys_config.get("vsync", True)
        self.fps   = sys_config.get("fps", 60)
        self.ipf   = sys_config.get("ipf", 100)

        # QUIRKS (see https://github.com/Timendus/chip8-test-suite/blob/main/README.md#quirks-test for more detail)
        quirk_config = (config or {}).get("QUIRKS", {})
        self.QUIRK_vF_reset  = quirk_config.get("vF_reset",  True)  # Reset VF register after bitwise operations
        self.QUIRK_memory    = quirk_config.get("memeory",   True)  # Increment I register when loading multiple registers into/from memory
        self.QUIRK_disp_wait = quirk_config.get("disp_wait", True)  # Wait for display refresh before drawing to prevent tearing (not neaded, purely for strict compatibility)
        self.QUIRK_disp_wait_faker = quirk_config.get("disp_wait_faker", False)  # Fake display refresh wait by updating timers (can break animations)
        self.QUIRK_clipping  = quirk_config.get("clipping",  True)  # Pixels clip instead of wrapping around the screen
        self.QUIRK_shifting  = quirk_config.get("shifting",  False) # Shift instructions shift VY instead of VX (result always stored in VX)
        self.QUIRK_jumping   = quirk_config.get("jumping",   False) # Jump instructions add VX to the address instead of V0

        # SYSTEM INIT
        self.screen = pygame.display.set_mode(
            self.output_resolution,
            flags=pygame.FULLSCREEN*self.fullscreen | pygame.RESIZABLE*self.resizable,
            vsync=self.vsync
        )
        pygame.display.set_caption("Chip8 Emulator")

        self.clock = pygame.time.Clock()
        self.font  = pygame.font.Font(None, 24)

        self.mem   = [0] * 4096 # 4KiB of memory
        self.regs  = [0] * 16  # 16 general purpose registers (8b)
        self.i_reg = 0        # I register (16b)
        self.pc    = 0x200       # Program counter (12b)

        # The stack size isn't defined in the original Chip-8 specification, 
        # the original COSMAC VIP interpreter used 48 bytes
        # (safe to increase if needed)
        self.stack = [0] * 48 # 24 levels (program counter takes 2 bytes)
        self.sp    = 0 # Stack pointer (8b)

        self.kb = [0] * 16

        # Keyboard layout
        # 1 2 3 4
        # Q W E R
        # A S D F
        # Z X C V

        # Keyboard mapping
        # idx: 0 1 2 3 4 5 6 7 8 9 A B C D E F
        # key: X 1 2 3 Q W E A S D Z C 4 R F V

        self.key_map = {
            pygame.K_1 : 0x1, pygame.K_2 : 0x2, pygame.K_3 : 0x3, pygame.K_4 : 0xc,
            pygame.K_q : 0x4, pygame.K_w : 0x5, pygame.K_e : 0x6, pygame.K_r : 0xd,
            pygame.K_a : 0x7, pygame.K_s : 0x8, pygame.K_d : 0x9, pygame.K_f : 0xe,
            pygame.K_z : 0xa, pygame.K_x : 0x0, pygame.K_c : 0xb, pygame.K_v : 0xf,
        }

        # TIMERS
        self.sound_timer = 0 # not implemented
        self.delay_timer = 0 # updated at screen refresh

        self.kb_interrupt = None
        self.interrupted = False

        self.disp = bytearray([0] * self.resolution[0] * self.resolution[1])

        self.load_sprites()

    def load_sprites(self):
        sprites = [
            0xF0, 0x90, 0x90, 0x90, 0xF0, # 0
            0x20, 0x60, 0x20, 0x20, 0x70, # 1
            0xF0, 0x10, 0xF0, 0x80, 0xF0, # 2
            0xF0, 0x10, 0xF0, 0x10, 0xF0, # 3
            0x90, 0x90, 0xF0, 0x10, 0x10, # 4
            0xF0, 0x80, 0xF0, 0x10, 0xF0, # 5
            0xF0, 0x80, 0xF0, 0x90, 0xF0, # 6
            0xF0, 0x10, 0x20, 0x40, 0x40, # 7
            0xF0, 0x90, 0xF0, 0x90, 0xF0, # 8
            0xF0, 0x90, 0xF0, 0x10, 0xF0, # 9
            0xF0, 0x90, 0xF0, 0x90, 0x90, # A
            0xE0, 0x90, 0xE0, 0x90, 0xE0, # B
            0xF0, 0x80, 0x80, 0x80, 0xF0, # C
            0xE0, 0x90, 0x90, 0x90, 0xE0, # D
            0xF0, 0x80, 0xF0, 0x80, 0xF0, # E
            0xF0, 0x80, 0xF0, 0x80, 0x80, # F
        ]

        for i, byte in enumerate(sprites):
            self.mem[i] = byte

    def load_rom(self, path):
        with open(path, "rb") as f:
            data = f.read()
            for i, byte in enumerate(data):
                self.mem[0x200 + i] = byte

    def set_pixel(self, x, y):
        if self.QUIRK_clipping:
            if x >= self.resolution[0] or y >= self.resolution[1]:
                return 1
            
            if x < 0 or y < 0:
                return 1

        pos = (x % self.resolution[0]) + (y % self.resolution[1]) * 64
        self.disp[pos] = int(not self.disp[pos])
        return int(not self.disp[pos])
    
    def cycle(self):
        time = pygame.time.get_ticks()
        self.handle_input()
        if self.ipf > 0:
            for _ in range(self.ipf):
                self.tick()
        else:
            target_fps = 1000 // self.fps

            while pygame.time.get_ticks() - time < target_fps:
                self.tick()

        self.update_timers()
        self.render()
    
    def handle_input(self):
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                exit()

            if ev.type == pygame.VIDEORESIZE:
                self.output_resolution = ev.size
            
            if ev.type == pygame.KEYDOWN:
                if ev.key in self.key_map:
                    self.kb[self.key_map[ev.key]] = 1
                    self.kb_interrupt = self.key_map[ev.key]

                if ev.key == pygame.K_m:
                    pygame.image.save(self.mem_to_surf(), "memory_dump.png")

            if ev.type == pygame.KEYUP:
                if ev.key in self.key_map:
                    self.kb[self.key_map[ev.key]] = 0

    def update_timers(self):
        if self.delay_timer > 0:
            self.delay_timer -= 1

        if self.sound_timer > 0:
            self.sound_timer -= 1

    def tick(self):
        opcode = self.mem[self.pc] << 8 | self.mem[self.pc + 1]

        x = (opcode & 0x0F00) >> 8
        y = (opcode & 0x00F0) >> 4

        self.pc += 2

        match opcode & 0xF000:
            case 0x0000:
                match opcode & 0x00FF:
                    case 0xE0:
                        self.disp = bytearray([0] * self.resolution[0] * self.resolution[1])

                    case 0xEE:
                        self.pc = self.stack[self.sp]
                        self.sp -= 1
                        self.sp %= len(self.stack)
                        self.pc <<= 8
                        self.pc |= self.stack[self.sp]
                        self.sp -= 1
                        self.sp %= len(self.stack)

            case 0x1000:
                self.pc = opcode & 0x0FFF

            case 0x2000:
                self.sp += 1
                self.sp %= len(self.stack)
                self.stack[self.sp] = self.pc & 0x00FF
                self.sp += 1
                self.sp %= len(self.stack)
                self.stack[self.sp] = self.pc >> 8
                
                self.pc = opcode & 0x0FFF

            case 0x3000:
                if self.regs[x] == opcode & 0x00FF:
                    self.pc += 2

            case 0x4000:
                if self.regs[x] != opcode & 0x00FF:
                    self.pc += 2

            case 0x5000:
                if self.regs[x] == self.regs[y]:
                    self.pc += 2

            case 0x6000:
                self.regs[x] = opcode & 0x00FF

            case 0x7000:
                self.regs[x] += opcode & 0x00FF
                self.regs[x] &= 0x00FF

            case 0x8000:
                match opcode & 0x000F:
                    case 0x0000:
                        self.regs[x] = self.regs[y]

                    case 0x0001:
                        self.regs[x] |= self.regs[y]
                        if self.QUIRK_vF_reset:
                            self.regs[0xF] = 0

                    case 0x0002:
                        self.regs[x] &= self.regs[y]
                        if self.QUIRK_vF_reset:
                            self.regs[0xF] = 0

                    case 0x0003:
                        self.regs[x] ^= self.regs[y]
                        if self.QUIRK_vF_reset:
                            self.regs[0xF] = 0

                    case 0x0004:
                        self.regs[x] += self.regs[y]
                        self.regs[0xF] = 1 if self.regs[x] > 0xFF else 0
                        self.regs[x] &= 0x00FF

                    case 0x0005:
                        self.regs[x] -= self.regs[y]
                        self.regs[0xF] = 0 if self.regs[x] < 0 else 1
                        self.regs[x] &= 0x00FF

                    case 0x0006:
                        if not self.QUIRK_shifting:
                            self.regs[x] = self.regs[y]

                        Rx = self.regs[x]
                        self.regs[x] >>= 1
                        self.regs[0xF] = Rx & 0x0001
                        self.regs[x] &= 0x00FF

                    case 0x0007:
                        self.regs[x] = self.regs[y] - self.regs[x]
                        self.regs[0xF] = 0 if self.regs[x] < 0 else 1
                        self.regs[x] &= 0x00FF

                    case 0x000E:
                        if not self.QUIRK_shifting:
                            self.regs[x] = self.regs[y]

                        Rx = self.regs[x]
                        self.regs[x] <<= 1
                        self.regs[0xF] = (Rx & 0x0080) >> 7
                        self.regs[x] &= 0x00FF

            case 0x9000:
                if self.regs[x] != self.regs[y]:
                    self.pc += 2

            case 0xA000:
                self.i_reg = opcode & 0x0FFF

            case 0xB000:
                self.pc = (opcode & 0x0FFF) + (self.regs[x] if self.QUIRK_jumping else self.regs[0])

            case 0xC000:
                self.regs[x] = random.randint(0, 255) & (opcode & 0x00FF)

            case 0xD000:
                if self.QUIRK_disp_wait:
                    if self.QUIRK_disp_wait_faker:
                        self.update_timers()
                    else:
                        if self.interrupted:
                            self.interrupted = False
                        else:
                            self.pc -= 2
                            return

                width  = 8
                height = opcode & 0x000F

                self.regs[0xF] = 0

                for row in range(height):
                    sprite = self.mem[self.i_reg + row]

                    for col in range(width):
                        if (sprite & 0x80) > 0:
                            if self.set_pixel(self.regs[x] % 64 + col, self.regs[y] % 32 + row):
                                self.regs[0xF] = 1

                        sprite <<= 1
                        sprite &= 0x00FF

            case 0xE000:
                match opcode & 0x00FF:
                    case 0x009E:
                        if self.kb[self.regs[x]]:
                            self.pc += 2

                    case 0x00A1:
                        if not self.kb[self.regs[x]]:
                            self.pc += 2

            case 0xF000:
                match opcode & 0x00FF:
                    case 0x0007:
                        self.regs[x] = self.delay_timer

                    case 0x000A:
                        if self.kb_interrupt is not None:
                            self.regs[x] = self.kb_interrupt
                            self.kb_interrupt = None

                        else:
                            self.pc -= 2
                            return
                    

                    case 0x0015:
                        self.delay_timer = self.regs[x]

                    case 0x0018:
                        self.sound_timer = self.regs[x]

                    case 0x001E:
                        self.i_reg += self.regs[x]
                        self.i_reg &= 0x0FFF

                    case 0x0029:
                        self.i_reg = self.regs[x] * 5
                        self.i_reg &= 0x0FFF

                    case 0x0033:
                        self.mem[self.i_reg + 0] = self.regs[x] // 100
                        self.mem[self.i_reg + 1] = (self.regs[x] % 100) // 10
                        self.mem[self.i_reg + 2] = self.regs[x] % 10

                    case 0x0055:
                        for i in range(x + 1):
                            self.mem[self.i_reg + i] = self.regs[i]

                        if self.QUIRK_memory:
                            self.i_reg += x + 1
                            self.i_reg &= 0x0FFF

                    case 0x0065:
                        for i in range(x + 1):
                            self.regs[i] = self.mem[self.i_reg + i]

                        if self.QUIRK_memory:
                            self.i_reg += x + 1
                            self.i_reg &= 0x0FFF

        self.kb_interrupt = None

    def render(self):
        self.screen.fill(self.bg_color)

        surf = pygame.image.frombuffer(self.disp, (self.resolution[0], self.resolution[1]), "P")
        surf.set_palette_at(0, self.off_color)
        surf.set_palette_at(1, self.on_color)

        available_res = list(self.output_resolution)
        if self.live_mem_view:
            available_res[0] -= 128 * self.mem_view_scale

        if self.preserve_aspect_ratio:
            out_scale = min(
                available_res[0] / self.resolution[0],
                available_res[1] / self.resolution[1]
            )

            if self.scaling_method == "nearest":
                surf = pygame.transform.scale_by(surf, out_scale)
            elif self.scaling_method == "smooth":
                surf = pygame.transform.smoothscale_by(surf.convert(), out_scale)
            else:
                raise Exception(f"Invalid scaling method: {self.scaling_method}")
        else:
            if self.scaling_method == "nearest":
                surf = pygame.transform.scale(surf, self.available_res)
            elif self.scaling_method == "smooth":
                surf = pygame.transform.smoothscale(surf.convert(), self.available_res)
            else:
                raise Exception(f"Invalid scaling method: {self.scaling_method}")

        self.screen.blit(surf, surf.get_rect(center=(available_res[0]//2, available_res[1]//2)))

        if self.live_mem_view:
            height = 0
            mem_txt = self.font.render(f"Memory:", True, self.on_color)
            self.screen.blit(
                mem_txt,
                (available_res[0], height)
            )
            height += mem_txt.get_height() + 5

            mem_dump = pygame.transform.scale_by(
                self.mem_to_surf(),
                self.mem_view_scale
            )
            self.screen.blit(
                mem_dump,
                (available_res[0], height),
            )
            height += mem_dump.get_height() + 5

            stack_txt = self.font.render(f"Stack:", True, self.on_color)
            self.screen.blit(
                stack_txt,
                (available_res[0], height)
            )
            height += stack_txt.get_height() + 5

            stack_dump = pygame.transform.scale_by(
                self.stack_to_surf(),
                self.mem_view_scale
            )
            self.screen.blit(
                stack_dump,
                (available_res[0], height),
            )
            height += stack_dump.get_height() + 5

            for i, reg in enumerate(self.regs):
                reg_txt = self.font.render(f"V{i:01X}: {reg:02X}", True, self.on_color)
                self.screen.blit(
                    reg_txt,
                    (available_res[0], height)
                )
                height += reg_txt.get_height() + 5

            i_reg_txt = self.font.render(f"I: {self.i_reg:04X}", True, self.on_color)
            self.screen.blit(
                i_reg_txt,
                (available_res[0], height)
            )
            height += i_reg_txt.get_height() + 5

        if self.show_fps:
            fps_txt = self.font.render(f"FPS: {self.clock.get_fps():.2f}", True, self.on_color)
            pygame.draw.rect(self.screen, self.bg_color, fps_txt.get_rect(topright = self.screen.get_rect().topright))
            self.screen.blit(
                fps_txt,
                fps_txt.get_rect(topright = self.screen.get_rect().topright)
            )

        pygame.display.flip()

        self.clock.tick(self.fps * (not self.vsync))

        self.interrupted = True

    def mem_to_surf(self):
        mem_dump = pygame.image.frombuffer(bytes(
            int(bit) for byte in self.mem for bit in bin(byte)[2:].zfill(8)
        ), (128, 256), "P")
        mem_dump.set_palette_at(0, self.off_color)
        mem_dump.set_palette_at(1, self.on_color)
        return mem_dump
    
    def stack_to_surf(self):
        stack_dump_size = len(self.stack) * 8
        stack_dump_width = 128
        if stack_dump_size % stack_dump_width == 0:
            stack_dump_height = stack_dump_size // stack_dump_width
        else:
            stack_dump_height = (stack_dump_size // stack_dump_width) + 1

        stack_copy = [0] * stack_dump_width * stack_dump_height
        for i, byte in enumerate(self.stack):
            for j in range(8):
                stack_copy[i*8 + j] = (byte >> j) & 1

        stack_copy = bytes(stack_copy)

        stack_dump = pygame.image.frombuffer(bytes(
            bit for bit in stack_copy
        ), (stack_dump_width, stack_dump_height), "P")

        stack_dump.set_palette_at(0, self.off_color)
        stack_dump.set_palette_at(1, self.on_color)
        return stack_dump                        

def main():
    config_path = os.path.join(os.path.dirname(__file__), "config.toml")
    config = {}
    if os.path.exists(config_path):
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
    
    emu = Emulator(config=config)

    emu.load_rom(sys.argv[1])

    while True:
        emu.cycle()

if __name__ == '__main__':
    main()
