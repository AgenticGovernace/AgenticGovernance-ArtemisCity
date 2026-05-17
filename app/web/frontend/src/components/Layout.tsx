/**
 * Layout Component for MCP Dashboard
 *
 * Provides the main layout structure with a responsive sidebar navigation.
 * On desktop, displays a fixed sidebar; on mobile, uses a drawer overlay.
 *
 * @module Layout
 */

import {
  Box,
  Flex,
  Link,
  Drawer,
  DrawerBody,
  DrawerOverlay,
  DrawerContent,
  DrawerCloseButton,
  useDisclosure,
  IconButton,
  VStack,
  Text,
  Heading,
  useBreakpointValue,
} from '@chakra-ui/react';
import { NavLink, Outlet } from 'react-router-dom';
import { GiHamburgerMenu } from 'react-icons/gi';

/**
 * Navigation item component for sidebar links.
 *
 * @param props - Component props
 * @param props.to - Route path for the link
 * @param props.children - Link text content
 * @returns Styled navigation link with active state highlighting
 */
const NavItem = ({ to, children }: { to: string; children: React.ReactNode }) => (
  <Link
    as={NavLink}
    to={to}
    px={3}
    py={2}
    rounded={'md'}
    _hover={{ textDecoration: 'none', bg: 'gray.700' }}
    _activeLink={{ bg: 'blue.500', color: 'white' }}
    width="100%"
  >
    {children}
  </Link>
);

/**
 * Main layout component with responsive sidebar navigation.
 *
 * Features:
 * - Fixed sidebar on desktop (md breakpoint and up)
 * - Drawer-based navigation on mobile
 * - Hamburger menu toggle for mobile
 * - Outlet for nested route content
 *
 * @returns The layout component with sidebar and content area
 */
const Layout = () => {
  const { isOpen, onOpen, onClose } = useDisclosure();
  const isDesktop = useBreakpointValue({ base: false, md: true });

  const SidebarContent = (
    <VStack spacing={4} align="stretch" px={4} py={8}>
      <Heading as="h1" size="lg" mb={4} color="white">
        MCP Dashboard
      </Heading>
      <NavItem to="/">Dashboard</NavItem>
      <NavItem to="/tasks">Tasks</NavItem>
      <NavItem to="/reports">Reports</NavItem>
      <NavItem to="/agents">Agents</NavItem>
      <Text fontSize="xs" color="gray.400" mt={2} px={3} fontWeight="bold">
        SYSTEM
      </Text>
      <NavItem to="/database">Database Viewer</NavItem>
      <NavItem to="/executor">CLI Executor</NavItem>
    </VStack>
  );

  return (
    <Flex minH="100vh" bg="gray.100">
      {isDesktop ? (
        <Box
          bg="gray.800"
          w="250px"
          minH="100vh"
          color="gray.100"
          p={4}
          borderRightWidth="1px"
          borderRightColor="gray.700"
        >
          {SidebarContent}
        </Box>
      ) : (
        <>
          <IconButton
            icon={<GiHamburgerMenu />}
            aria-label="Open Menu"
            onClick={onOpen}
            position="fixed"
            top="4"
            left="4"
            zIndex="overlay"
            bg="gray.800"
            color="white"
          />
          <Drawer isOpen={isOpen} placement="left" onClose={onClose}>
            <DrawerOverlay />
            <DrawerContent bg="gray.800" color="gray.100">
              <DrawerCloseButton />
              <DrawerBody>{SidebarContent}</DrawerBody>
            </DrawerContent>
          </Drawer>
        </>
      )}

      <Box flex="1" p={isDesktop ? 8 : 4} ml={!isDesktop && isOpen ? '250px' : '0'}>
        <Outlet />
      </Box>
    </Flex>
  );
};

export default Layout;
